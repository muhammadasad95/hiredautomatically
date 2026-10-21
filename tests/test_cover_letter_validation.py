import unittest

from claude_engine import validate_cover_letter, validate_regenerated_cover_letter


class CoverLetterValidationTests(unittest.TestCase):
    def test_accepts_letter_that_names_target_company(self):
        data = {"cover_letter": "I am applying to the Principal Engineer role at Pearson."}
        self.assertEqual(validate_cover_letter(data, "Pearson"), data["cover_letter"])

    def test_company_match_is_case_insensitive(self):
        self.assertTrue(
            validate_cover_letter({"cover_letter": "I am interested in PEARSON."}, "Pearson")
        )

    def test_rejects_wrong_company(self):
        data = {"cover_letter": "I am applying to a role at eDynamic Learning."}
        with self.assertRaisesRegex(ValueError, "does not name the target hiring company"):
            validate_cover_letter(data, "Pearson")

    def test_rejects_empty_letter_or_target_company(self):
        with self.assertRaisesRegex(ValueError, "non-empty cover letter"):
            validate_cover_letter({"cover_letter": "  "}, "Pearson")
        with self.assertRaisesRegex(ValueError, "Target company is missing"):
            validate_cover_letter({"cover_letter": "A professional letter."}, " ")

    def test_rejects_overly_long_letter(self):
        with self.assertRaisesRegex(ValueError, "exceeds 180 words"):
            validate_regenerated_cover_letter(
                {"cover_letter": "Pearson " + "word " * 200}, "Pearson"
            )

    def test_accepts_regenerated_letter_within_word_cap(self):
        letter = "Pearson role. " + "word " * 150
        self.assertEqual(
            validate_regenerated_cover_letter({"cover_letter": letter}, "Pearson"),
            letter,
        )


if __name__ == "__main__":
    unittest.main()
