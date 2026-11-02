# -*- coding: utf-8 -*-
"""Tests for currentsmap.common and currentsmap.directions. Run from the
repository root with:

    python -m unittest discover -s toolboxes/currents_map/tests
"""

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from currentsmap import common, currents, directions  # noqa: E402


class CommonTests(unittest.TestCase):
    def test_gdb_name_for(self):
        self.assertEqual(common.gdb_name_for(r"C:\data\Ungoofaaru currents 15-10.csv"),
                         "Ungoofaaru_currents_15_10")
        self.assertEqual(common.gdb_name_for("15-10 currents.csv"), "Currents_15_10_currents")
        self.assertEqual(common.gdb_name_for("---.csv"), "Currents_Data")

    def test_zoom_extent_adds_a_margin(self):
        self.assertEqual(common.zoom_extent(0, 0, 1000, 400), (-250, -250, 1250, 650))

    def test_zoom_extent_is_never_too_small(self):
        xmin, ymin, xmax, ymax = common.zoom_extent(100, 100, 110, 100)
        self.assertEqual((xmax - xmin, ymax - ymin), (200, 200))
        self.assertEqual(((xmin + xmax) / 2, (ymin + ymax) / 2), (105, 100))
        # In degrees, 200 m is about 0.0018 of a degree.
        xmin, _, xmax, _ = common.zoom_extent(73.0, 5.6, 73.0, 5.6, 111320.0)
        self.assertAlmostEqual(xmax - xmin, 200 / 111320.0)

    def test_name_prefix(self):
        self.assertEqual(common.name_prefix("C1 start"), "C")
        self.assertEqual(common.name_prefix(" c12 end"), "C")
        self.assertEqual(common.name_prefix("12"), "")


class DirectionTests(unittest.TestCase):
    def test_compass_points(self):
        for bearing, point in ((0, "N"), (181, "S"), (103, "ESE"), (348.75, "N"), (348.7, "NNW")):
            with self.subTest(bearing=bearing):
                self.assertEqual(directions.compass_point(bearing), point)

    def test_bearing_to(self):
        self.assertEqual(directions.bearing_to(0, 1), 0)
        self.assertEqual(directions.bearing_to(1, 0), 90)
        self.assertEqual(directions.bearing_to(0, -1), 180)
        self.assertEqual(directions.bearing_to(-1, 0), 270)


class PointValueTests(unittest.TestCase):
    def test_start_and_end_points(self):
        start = currents.Reading("C1 start", 0, 0, 4326, datetime(2026, 10, 15, 14, 13))
        end = currents.Reading("C1 end", 0, 0, 4326, datetime(2026, 10, 15, 14, 18))
        values = currents.point_values(currents.Current("C1", start, end))
        self.assertEqual(values, [
            ("C1 start", ("C1", "Start", start.time)),
            ("C1 end", ("C1", "End", end.time)),
        ])
        self.assertEqual(len(values[0][1]), len(currents.POINT_FIELDS))


if __name__ == "__main__":
    unittest.main()
