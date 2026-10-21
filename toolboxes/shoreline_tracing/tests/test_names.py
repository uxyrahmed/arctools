# -*- coding: utf-8 -*-
"""Tests for shoreline.names. Run from the repository root with:

    python -m unittest discover -s toolboxes/shoreline_tracing/tests
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shoreline import names  # noqa: E402


class NameTests(unittest.TestCase):
    def test_safe_and_unique_names(self):
        self.assertEqual(names.safe_name(r"C:\drone\Olhuveli 200m (7cm).tif"), "Olhuveli_200m_7cm")
        self.assertEqual(names.unique_names(["a/Ortho.tif", "b/ortho.tif", "c/x.tif"]),
                         ["Ortho", "ortho_2", "x"])

    def test_training_folders(self):
        with tempfile.TemporaryDirectory() as root:
            for survey in ("Orimasvaru", "Emerald"):
                os.makedirs(os.path.join(root, survey, "images"))
                os.makedirs(os.path.join(root, survey, "labels"))
            os.makedirs(os.path.join(root, "zones.gdb"))
            found = names.training_folders(root)
            self.assertEqual([os.path.basename(p) for p in found], ["Emerald", "Orimasvaru"])
            self.assertEqual(names.training_folders(found[0]), [found[0]])
            self.assertEqual(names.training_folders(os.path.join(root, "missing")), [])

    def test_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(names.read_settings(root), {})
            names.write_settings(root, {"cell_size": 0.15})
            self.assertEqual(names.read_settings(root), {"cell_size": 0.15})

    def test_find_line_file(self):
        with tempfile.TemporaryDirectory() as root:
            for entry in ("Low Tide Line.shp", "high_tide_line.shp", "Vegetation Line.dbf"):
                open(os.path.join(root, entry), "w").close()
            self.assertTrue(names.find_line_file(root, names.LOW_TIDE).endswith("Low Tide Line.shp"))
            self.assertTrue(names.find_line_file(root, names.HIGH_TIDE).endswith("high_tide_line.shp"))
            self.assertIsNone(names.find_line_file(root, names.VEGETATION))


if __name__ == "__main__":
    unittest.main()
