# -*- coding: utf-8 -*-
"""Tests for surveymap.currents. Run from the repository root with:

    python -m unittest discover -s toolboxes/survey_location_map/tests
"""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from surveymap import currents  # noqa: E402
from surveymap.surveys import SurveyMapError  # noqa: E402

# The currents CSV from R. Ungoofaaru, as the field device writes it: UTF-8
# with a byte order mark, Windows line endings.
UNGOOFAARU = (
    "﻿Name,Latitude,Longitude,UTM,Date Record\r\n"
    "C1 start,5.668124596,73.03368956,282219.358E 626887.752N 43N,15/10/2026 14:13\r\n"
    "C1 end,5.667565087,73.03367984,282218.071E 626825.871N 43N,15/10/2026 14:18\r\n"
    "C2 start,5.664827254,73.02809615,281598.373E 626525.152N 43N,15/10/2026 14:54\r\n"
    "C2 end,5.66478655,73.02827351,281618.01E 626520.583N 43N,15/10/2026 14:59\r\n"
)


def reading(name, minute, x=0.0, y=0.0):
    return currents.Reading(name, x, y, 4326, datetime(2026, 10, 15, 14, minute))


class CsvTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.folder)

    def write(self, text, encoding="utf-8"):
        path = os.path.join(self.folder, "currents.csv")
        with open(path, "w", encoding=encoding, newline="") as stream:
            stream.write(text)
        return path

    def test_field_device_csv(self):
        readings, problems = currents.read_csv(self.write(UNGOOFAARU))
        self.assertEqual(problems, [])
        self.assertEqual([r.name for r in readings], ["C1 start", "C1 end", "C2 start", "C2 end"])
        first = readings[0]
        self.assertEqual((first.x, first.y, first.wkid), (73.03368956, 5.668124596, 4326))
        self.assertEqual(first.time, datetime(2026, 10, 15, 14, 13))

    def test_utm_when_there_is_no_latitude_and_longitude(self):
        text = "Name,UTM,Date Record\nC1 start,282219.358E 626887.752N 43N,15/10/2026 14:13\n"
        readings, _ = currents.read_csv(self.write(text))
        self.assertEqual(readings[0][1:4], (282219.358, 626887.752, 32643))

    def test_separate_date_and_time_columns_and_semicolons(self):
        text = "Name;Lat;Lon;Date;Time\nC1 start;5,668;73,033;15/10/2026;14:13:30\n"
        readings, _ = currents.read_csv(self.write(text))
        self.assertEqual(readings[0].time, datetime(2026, 10, 15, 14, 13, 30))
        self.assertEqual((readings[0].x, readings[0].y), (73.033, 5.668))

    def test_windows_encoding(self):
        text = "Name,Latitude,Longitude,Date Record\nC1 départ,5.66,73.03,15/10/2026 14:13\n"
        readings, _ = currents.read_csv(self.write(text, encoding="cp1252"))
        self.assertEqual(readings[0].name, "C1 départ")

    def test_bad_rows_are_left_out_with_a_reason(self):
        text = UNGOOFAARU + "C3 start,,,,15/10/2026 15:00\r\nC3 end,5.66,73.03,,soon\r\n,5.66,73.03,,\r\n"
        readings, problems = currents.read_csv(self.write(text))
        self.assertEqual(len(readings), 4)
        self.assertEqual(len(problems), 3)
        self.assertIn("C3 start has no position", problems[0])
        self.assertIn("'soon'", problems[1])
        self.assertIn("Row 8", problems[2])

    def test_missing_columns(self):
        for text, missing in (
            ("Label,Latitude,Longitude,Date\n", "Name column"),
            ("Name,Date Record\n", "Latitude and Longitude"),
            ("Name,Latitude,Longitude\n", "date and time"),
        ):
            with self.subTest(missing=missing):
                with self.assertRaises(SurveyMapError) as caught:
                    currents.read_csv(self.write(text + "C1 start,5.66,73.03\n"))
                self.assertIn(missing, str(caught.exception))

    def test_empty_and_missing_files(self):
        with self.assertRaises(SurveyMapError):
            currents.read_csv(self.write(""))
        with self.assertRaises(SurveyMapError):
            currents.read_csv(os.path.join(self.folder, "gone.csv"))


class TimeTests(unittest.TestCase):
    def test_formats(self):
        expected = datetime(2026, 10, 15, 14, 13)
        for text in ("15/10/2026 14:13", "15-10-2026 14:13", "2026-10-15 14:13:00",
                     "2026-10-15T14:13", "2026-10-15T14:13:00Z", "15/10/2026 2:13 PM",
                     "10/15/2026 2:13 PM", "15-Oct-2026 14:13", " 15/10/2026   14:13 "):
            with self.subTest(text=text):
                self.assertEqual(currents.parse_time(text), expected)

    def test_time_zones_become_utc(self):
        self.assertEqual(currents.parse_time("2026-10-15T19:13:00+05:00"),
                         datetime(2026, 10, 15, 14, 13))

    def test_not_a_time(self):
        for text in ("", None, "soon", "15/10/2026", "32/10/2026 14:13"):
            with self.subTest(text=text):
                self.assertIsNone(currents.parse_time(text))


class UtmTests(unittest.TestCase):
    def test_zones_and_hemispheres(self):
        self.assertEqual(currents._utm("282219.358E 626887.752N 43N"), (282219.358, 626887.752, 32643))
        self.assertEqual(currents._utm("282219.358E 9936887.752N 43S")[2], 32743)
        self.assertEqual(currents._utm("282219.358E 9936887.752N 43M")[2], 32743)
        self.assertEqual(currents._utm("282219 E, 626887 N, 43")[2], 32643)
        self.assertIsNone(currents._utm("not a position"))
        self.assertIsNone(currents._utm("1E 2N 61N"))


class PairingTests(unittest.TestCase):
    def test_split_name(self):
        for name, expected in (("C1 start", ("C1", "start")), ("C1 End", ("C1", "end")),
                               ("C1_START", ("C1", "start")), ("C2end", ("C2", "end")),
                               ("C 3 finish", ("C 3", "end")), ("C4", ("C4", None)),
                               ("start", ("start", None))):
            with self.subTest(name=name):
                self.assertEqual(currents.split_name(name), expected)

    def test_pairs_in_natural_order(self):
        found, problems = currents.pair_readings([
            reading("C10 end", 20), reading("C2 start", 0), reading("C10 start", 15),
            reading("C2 end", 5),
        ])
        self.assertEqual(problems, [])
        self.assertEqual([c.name for c in found], ["C2", "C10"])
        self.assertEqual((found[1].start.name, found[1].end.name), ("C10 start", "C10 end"))

    def test_only_current_points(self):
        readings = [reading("SW101", 0), reading("C1 start", 1), reading("C1 end", 6)]
        kept, others = currents.only_currents(readings)
        self.assertEqual(([r.name for r in kept], others), (["C1 start", "C1 end"], 1))
        drogues = [reading("D1 start", 0), reading("D1 end", 5)]
        self.assertEqual(currents.only_currents(drogues), (drogues, 0))

    def test_points_named_alike_go_in_time_order(self):
        found, _ = currents.pair_readings([reading("C1", 10), reading("C1", 5)])
        self.assertEqual((found[0].start.time.minute, found[0].end.time.minute), (5, 10))

    def test_problems(self):
        found, problems = currents.pair_readings([
            reading("C1 start", 0), reading("C2 start", 0), reading("C2 end", 0),
            reading("C3 start", 10), reading("C3 end", 5),
            reading("C4 start", 0), reading("C4 end", 5), reading("C4 end", 6),
        ])
        self.assertEqual(found, [])
        self.assertEqual(len(problems), 4)
        self.assertIn("C1 needs one start and one end point", problems[0])
        self.assertIn("C2 ends at 14:00, which isn't after it starts", problems[1])
        self.assertIn("C3 ends at 14:05", problems[2])
        self.assertIn("C4 end, C4 end", problems[3])


class MeasureTests(unittest.TestCase):
    def test_ungoofaaru(self):
        # C1 and C2 moved this far east and north in UTM Zone 43N, in 5 minutes.
        c1 = currents.Current("C1", reading("C1 start", 13), reading("C1 end", 18))
        values = currents.measure(c1, -1.287, -61.881)
        self.assertEqual(values["Label"], "0.21 m/s S")
        self.assertEqual(values["Bearing"], 181.2)
        self.assertEqual(values["Direction"], "S")
        self.assertEqual(values["Distance_m"], 61.89)
        self.assertEqual(values["Minutes"], 5.0)
        self.assertEqual(list(values), [field for field, _ in currents.ARROW_FIELDS])
        c2 = currents.Current("C2", reading("C2 start", 54), reading("C2 end", 59))
        self.assertEqual(currents.measure(c2, 19.637, -4.569)["Label"], "0.07 m/s ESE")
        self.assertEqual(
            currents.describe("C1", values),
            "C1: 61.9 m in 5 min, 0.21 m/s S (bearing 181\N{DEGREE SIGN})",
        )

    def test_no_movement_has_no_direction(self):
        c = currents.Current("C1", reading("C1 start", 0), reading("C1 end", 5))
        values = currents.measure(c, 0.0, 0.0)
        self.assertEqual((values["Label"], values["Bearing"], values["Direction"]),
                         ("0.00 m/s", None, ""))


if __name__ == "__main__":
    unittest.main()
