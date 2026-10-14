"""Regression tests for summary lengths and their budgets.

Run from the repo root:  .venv/bin/python -m unittest discover -s backend/tests -v
"""
import unittest

from backend.prompts import LENGTHS, MAX_TOKENS, PROMPTS, build_prompt, normalize_length


class LengthTests(unittest.TestCase):
    def test_every_length_has_prompt_and_budget(self):
        for length in LENGTHS:
            self.assertIn(length, PROMPTS)
            self.assertGreater(MAX_TOKENS.get(length, 0), 0)
            prompt = build_prompt(length, "Title", "transcript")
            self.assertIn("transcript", prompt)

    def test_budgets_grow_with_length(self):
        budgets = [MAX_TOKENS[length] for length in LENGTHS]
        self.assertEqual(budgets, sorted(budgets))

    def test_extended_targets_1200_to_1600_words(self):
        self.assertIn("extended", LENGTHS)
        self.assertIn("1200-1600", PROMPTS["extended"])
        # ~1600 words needs well over 2000 output tokens of headroom.
        self.assertGreaterEqual(MAX_TOKENS["extended"], 4000)

    def test_aliases(self):
        self.assertEqual(normalize_length("xl"), "extended")
        self.assertEqual(normalize_length("mid"), "medium")
        self.assertEqual(normalize_length(" Long "), "long")

    def test_unknown_length_rejected(self):
        with self.assertRaises(ValueError):
            normalize_length("bogus")


if __name__ == "__main__":
    unittest.main()
