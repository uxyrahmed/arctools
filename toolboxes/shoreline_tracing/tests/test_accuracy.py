# -*- coding: utf-8 -*-
"""Tests for shoreline.accuracy. Run from the repository root with:

    python -m unittest discover -s toolboxes/shoreline_tracing/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shoreline import accuracy  # noqa: E402


class SummariseTests(unittest.TestCase):
    def test_summary(self):
        result = accuracy.summarise([0.2, 0.4, 0.6, 1.5, 3.0])
        self.assertEqual(result["count"], 5)
        self.assertAlmostEqual(result["mean"], 1.14)
        self.assertAlmostEqual(result["median"], 0.6)
        self.assertAlmostEqual(result["max"], 3.0)
        self.assertAlmostEqual(result["within_0.5"], 0.4)
        self.assertAlmostEqual(result["within_1"], 0.6)
        self.assertAlmostEqual(result["within_2"], 0.8)
        self.assertAlmostEqual(result["p90"], 2.4)

    def test_missing_distances_are_left_out(self):
        result = accuracy.summarise([None, float("nan"), 1.0])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["median"], 1.0)

    def test_empty(self):
        self.assertEqual(accuracy.summarise([]), {"count": 0})
        self.assertIn("nothing to compare", accuracy.report_line("Low Tide Line", {"count": 0}))

    def test_report_line(self):
        line = accuracy.report_line("High Tide Line", accuracy.summarise([0.5, 1.0]))
        self.assertTrue(line.startswith("High Tide Line: typical gap 0.75 m"))
        self.assertIn("100% within 1 m", line)


if __name__ == "__main__":
    unittest.main()
