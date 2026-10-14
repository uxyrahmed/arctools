# -*- coding: utf-8 -*-
"""Tests for surveymap.directions. Run from the repository root with:

    python -m unittest discover -s toolboxes/survey_location_map/tests
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from surveymap import directions  # noqa: E402
from surveymap.directions import parse_direction  # noqa: E402


class BearingTests(unittest.TestCase):
    def test_sixteen_points(self):
        self.assertEqual(len(directions.BEARINGS), 16)
        self.assertEqual(directions.BEARINGS["N"], 0)
        self.assertEqual(directions.BEARINGS["NE"], 45)
        self.assertEqual(directions.BEARINGS["E"], 90)
        self.assertEqual(directions.BEARINGS["SSW"], 202.5)
        self.assertEqual(directions.BEARINGS["NNW"], 337.5)


class ParseDirectionTests(unittest.TestCase):
    def test_sample_names(self):
        self.assertEqual(parse_direction("T201 S 2m"), 180)
        self.assertEqual(parse_direction("T202 S 3m"), 180)
        self.assertEqual(parse_direction("T203 N 4m"), 0)

    def test_every_compass_point(self):
        for point, bearing in directions.BEARINGS.items():
            for name in (f"T1 {point} 2m", f"T1 {point.lower()}", f"T1 {point}2m"):
                with self.subTest(name=name):
                    self.assertEqual(parse_direction(name), bearing)

    def test_depth_written_into_the_direction(self):
        self.assertEqual(parse_direction("T204 NE3.5m"), 45)
        self.assertEqual(parse_direction("T204 SW10M"), 225)
        self.assertEqual(parse_direction("T204 E5"), 90)

    def test_words(self):
        cases = {
            "T1 north": 0,
            "T1 South 2m": 180,
            "T1 EAST": 90,
            "T1 west 3 m": 270,
            "T1 southeast": 135,
            "T1 North-West 2m": 315,
            "T1 south east": 135,
            "T1 North West": 315,
        }
        for name, bearing in cases.items():
            with self.subTest(name=name):
                self.assertEqual(parse_direction(name), bearing)

    def test_separators(self):
        cases = {
            "T1_S_2m": 180,
            "T1-NE-3m": 45,
            "T1, SE, 2m": 135,
            "T1 (SW) 2 m": 225,
            "T1 [W]": 270,
            "T1 N.": 0,
            "T1/ESE/4m": 112.5,
        }
        for name, bearing in cases.items():
            with self.subTest(name=name):
                self.assertEqual(parse_direction(name), bearing)

    def test_no_direction(self):
        for name in ("T201", "T201 2m", "T201 deep", "", None, "T1 3.5 m", "T1 start"):
            with self.subTest(name=name):
                self.assertIsNone(parse_direction(name))

    def test_first_word_is_the_id(self):
        # The ID is never read as a direction, even when it is a compass letter.
        self.assertIsNone(parse_direction("S1"))
        self.assertIsNone(parse_direction("E"))
        self.assertIsNone(parse_direction("N1 2m"))
        self.assertEqual(parse_direction("N1 S 2m"), 180)

    def test_words_that_only_start_like_a_direction(self):
        for name in ("T1 Sand 2m", "T1 seaward", "T1 new", "T1 Ends", "T1 wester",
                     "T1 northern", "T1 Nearshore", "T1 SEA"):
            with self.subTest(name=name):
                self.assertIsNone(parse_direction(name))

    def test_first_direction_wins(self):
        self.assertEqual(parse_direction("T1 S then E"), 180)


class OffsetTests(unittest.TestCase):
    def assertPoint(self, actual, expected):
        self.assertAlmostEqual(actual[0], expected[0], places=9)
        self.assertAlmostEqual(actual[1], expected[1], places=9)

    def test_cardinal_points(self):
        self.assertPoint(directions.offset(100.0, 200.0, 0, 50), (100.0, 250.0))
        self.assertPoint(directions.offset(100.0, 200.0, 90, 50), (150.0, 200.0))
        self.assertPoint(directions.offset(100.0, 200.0, 180, 50), (100.0, 150.0))
        self.assertPoint(directions.offset(100.0, 200.0, 270, 50), (50.0, 200.0))

    def test_north_east(self):
        side = 50 / math.sqrt(2)
        self.assertPoint(directions.offset(0.0, 0.0, 45, 50), (side, side))

    def test_length_is_kept(self):
        for bearing in directions.BEARINGS.values():
            x, y = directions.offset(310000.0, 425000.0, bearing, 50.0)
            self.assertAlmostEqual(math.hypot(x - 310000.0, y - 425000.0), 50.0, places=6)

    def test_sample_transect(self):
        # T201 S 2m runs 50 m due south of the point.
        x, y = directions.offset(310897.3, 425693.1, parse_direction("T201 S 2m"), 50.0)
        self.assertPoint((x, y), (310897.3, 425643.1))


if __name__ == "__main__":
    unittest.main()
