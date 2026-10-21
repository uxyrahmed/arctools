# -*- coding: utf-8 -*-
"""Tests for shoreline.labels. Run from the repository root with:

    python -m unittest discover -s toolboxes/shoreline_tracing/tests
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shoreline import labels  # noqa: E402
from shoreline.labels import DRY_BEACH, INTERTIDAL, NO_LABEL, VEGETATION, WATER  # noqa: E402


def disc(size, radius):
    """True inside a circle of radius cells at the centre of a size grid."""
    rows, cols = np.mgrid[:size, :size]
    centre = (size - 1) / 2
    return np.hypot(rows - centre, cols - centre) <= radius


def ring(size, radius):
    """A one-cell-wide circle, like a high tide line drawn onto a grid."""
    rows, cols = np.mgrid[:size, :size]
    centre = (size - 1) / 2
    return np.abs(np.hypot(rows - centre, cols - centre) - radius) < 0.5


class IslandTests(unittest.TestCase):
    """A round island: low tide radius 40, high tide 30, vegetation 20 cells."""

    def setUp(self):
        self.size = 101
        self.low = disc(self.size, 40)
        self.veg = disc(self.size, 20)
        self.high = ring(self.size, 30)

    def zones(self, **kwargs):
        options = dict(high_tide_reach=50, sea_band=100, land_band=100)
        options.update(kwargs)
        return labels.make_labels(self.low, self.veg, self.high, 1.0, **options)

    def at(self, zones, radius):
        """Zone at radius cells east of the centre."""
        centre = self.size // 2
        return zones[centre, centre + radius]

    def test_zones_from_sea_to_vegetation(self):
        zones = self.zones()
        self.assertEqual(self.at(zones, 45), WATER)
        self.assertEqual(self.at(zones, 35), INTERTIDAL)
        self.assertEqual(self.at(zones, 25), DRY_BEACH)
        self.assertEqual(self.at(zones, 10), VEGETATION)

    def test_gap_in_high_tide_line_still_labels_nearby_beach(self):
        # Cut the eastern quarter out of the high tide line.
        rows, cols = np.mgrid[:self.size, :self.size]
        self.high &= ~(cols > self.size // 2 + 20)
        zones = self.zones(high_tide_reach=50)
        self.assertEqual(self.at(zones, 35), INTERTIDAL)
        self.assertEqual(self.at(zones, 25), DRY_BEACH)

    def test_beach_far_from_any_high_tide_line_gets_no_label(self):
        rows, cols = np.mgrid[:self.size, :self.size]
        self.high &= cols < 20  # only a short western piece
        zones = self.zones(high_tide_reach=10)
        self.assertEqual(self.at(zones, 35), NO_LABEL)
        self.assertEqual(self.at(zones, 45), WATER)
        self.assertEqual(self.at(zones, 10), VEGETATION)

    def test_no_high_tide_line_leaves_beach_unlabelled(self):
        self.high[:] = False
        zones = self.zones()
        self.assertEqual(self.at(zones, 35), NO_LABEL)
        self.assertEqual(self.at(zones, 25), NO_LABEL)
        self.assertEqual(self.at(zones, 45), WATER)

    def test_bands_drop_deep_water_and_interior(self):
        zones = self.zones(sea_band=5, land_band=30)
        self.assertEqual(self.at(zones, 44), WATER)
        self.assertEqual(self.at(zones, 50), NO_LABEL)
        self.assertEqual(self.at(zones, 15), VEGETATION)
        self.assertEqual(self.at(zones, 5), NO_LABEL)

    def test_cell_size_scales_distances(self):
        # Same grid, 0.5 m cells: a 10 m sea band is 20 cells.
        zones = labels.make_labels(self.low, self.veg, self.high, 0.5,
                                   sea_band=10, land_band=100)
        self.assertEqual(self.at(zones, 50), WATER)
        zones = labels.make_labels(self.low, self.veg, self.high, 0.5,
                                   sea_band=4, land_band=100)
        self.assertEqual(self.at(zones, 50), NO_LABEL)

    def test_vegetation_outside_low_tide_is_ignored(self):
        self.veg |= disc(self.size, 45) & ~disc(self.size, 43)
        zones = self.zones()
        self.assertEqual(self.at(zones, 44), WATER)

    def test_no_low_tide_line_gives_no_labels(self):
        zones = labels.make_labels(np.zeros((5, 5), bool), np.zeros((5, 5), bool),
                                   np.zeros((5, 5), bool), 1.0)
        self.assertFalse(zones.any())

    def test_grids_must_match(self):
        with self.assertRaises(ValueError):
            labels.make_labels(np.zeros((5, 5), bool), np.zeros((4, 5), bool),
                               np.zeros((5, 5), bool), 1.0)

    def test_counts_and_mask(self):
        zones = self.zones()
        counts = labels.class_counts(zones)
        self.assertEqual(sum(counts.values()), self.size * self.size)
        self.assertGreater(counts["Intertidal"], 0)
        self.assertEqual(labels.train_mask(zones).sum(),
                         self.size * self.size - counts["No label"])


if __name__ == "__main__":
    unittest.main()
