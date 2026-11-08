# -*- coding: utf-8 -*-
"""Tests for surveymap.surveys. Run from the repository root with:

    python -m unittest discover -s toolboxes/survey_location_map/tests
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from surveymap import surveys  # noqa: E402
from surveymap.surveys import POINT, POLYLINE  # noqa: E402

# Point and line names from the sample KMZ (Masterplan changes surveyed 2.kmz),
# with the survey each should land in.
SAMPLE_POINTS = {
    "T201 S 2m": "T",
    "T202 S 3m": "T",
    "T203 N 4m": "T",
    "VSS201": "VSS",
    "VSS206": "VSS",
    "P1": "BP",
    "P10": "BP",
    "C201 start": "C",
    "C202 end": "C",
    "SW201": "SW",
    "SW207": "SW",
}
SAMPLE_LINES = {"VSS1": "VSS_LINES", "VSS6": "VSS_LINES"}


class SurveyTableTests(unittest.TestCase):
    def test_codes_and_feature_classes_are_unique(self):
        codes = [s.code for s in surveys.SURVEYS]
        feature_classes = [s.feature_class for s in surveys.SURVEYS]
        layer_names = [surveys.normalise(s.layer_name) for s in surveys.SURVEYS]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(len(feature_classes), len(set(feature_classes)))
        self.assertEqual(len(layer_names), len(set(layer_names)))

    def test_feature_class_names_are_valid_in_a_geodatabase(self):
        for survey in surveys.SURVEYS:
            self.assertRegex(survey.feature_class, r"^[A-Za-z][A-Za-z0-9_]*$")

    def test_prefixes_are_capital_letters(self):
        for survey in surveys.SURVEYS:
            for prefix in survey.prefixes:
                self.assertRegex(prefix, r"^[A-Z]+$")

    def test_no_prefix_belongs_to_two_surveys_of_one_geometry(self):
        seen = {}
        for survey in surveys.SURVEYS:
            for prefix in survey.prefixes:
                key = (prefix, survey.geometry)
                self.assertNotIn(key, seen, f"{prefix} is used by {seen.get(key)} too")
                seen[key] = survey.code

    def test_point_surveys_have_tables_and_headings(self):
        for survey in surveys.SURVEYS:
            if survey.is_point:
                self.assertEqual(survey.table_name, survey.code + " Table")
                self.assertEqual(survey.heading_name, survey.code + " Heading")
            else:
                self.assertIsNone(survey.table_name)
                self.assertIsNone(survey.heading_name)

    def test_point_survey_order(self):
        self.assertEqual(
            [s.code for s in surveys.point_surveys()],
            ["SW", "VSS", "T", "BP", "GW", "C", "N"],
        )

    def test_transect_codes(self):
        self.assertEqual(surveys.by_code(surveys.TRANSECT_POINTS).geometry, POINT)
        transect_lines = surveys.by_code(surveys.TRANSECT_LINES)
        self.assertEqual(transect_lines.geometry, POLYLINE)
        # Transect lines in the KMZ are named like the points, and are kept.
        self.assertEqual(transect_lines.prefixes, ("T",))
        self.assertNotIn(
            surveys.TRANSECT_LINES_FROM_KMZ, [s.feature_class for s in surveys.SURVEYS]
        )

    def test_by_code_unknown(self):
        with self.assertRaises(KeyError):
            surveys.by_code("MT")

    def test_layer_names(self):
        self.assertEqual(
            [s.layer_name for s in surveys.SURVEYS],
            [
                "Sea Water Sampling Points",
                "Visual Snorkeling Survey Points",
                "Visual Snorkeling Survey Lines",
                "Marine Transects",
                "Transect Line",
                "Beach Profiles",
                "Ground Water Sampling Points",
                "Currents Survey Points",
                "Currents",
                "Noise Survey Points",
            ],
        )

    def test_current_codes(self):
        self.assertEqual(surveys.by_code(surveys.CURRENT_POINTS).geometry, POINT)
        arrows = surveys.by_code(surveys.CURRENT_ARROWS)
        self.assertEqual(arrows.geometry, POLYLINE)
        # Drawn from the currents CSV, so no KMZ feature goes into them.
        self.assertEqual(arrows.prefixes, ())
        self.assertIsNone(arrows.table_name)

    def test_arrows_replace_current_points_on_the_map(self):
        self.assertEqual(
            surveys.layers_to_show({"SW": 6, "C": 4, "C_ARROWS": 2}), {"SW", "C_ARROWS"}
        )
        self.assertEqual(surveys.layers_to_show({"SW": 6, "C": 4}), {"SW", "C"})
        self.assertEqual(surveys.layers_to_show({}), set())

    def test_label_fields(self):
        self.assertEqual(surveys.label_field(surveys.by_code("SW")), "Name")
        self.assertEqual(surveys.label_field(surveys.by_code("C_ARROWS")), "Label")
        self.assertIsNone(surveys.label_field(surveys.by_code("T_LINES")))
        self.assertIsNone(surveys.label_field(surveys.by_code("VSS_LINES")))


class NamePrefixTests(unittest.TestCase):
    def test_prefixes(self):
        cases = {
            "SW201": "SW",
            "T201 S 2m": "T",
            "C202 start": "C",
            " vss3": "VSS",
            "bp-4": "BP",
            "GW1": "GW",
            "12": "",
            "": "",
            None: "",
            "#5": "",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(surveys.name_prefix(name), expected)


class SurveyForTests(unittest.TestCase):
    def test_sample_points(self):
        for name, code in SAMPLE_POINTS.items():
            with self.subTest(name=name):
                self.assertEqual(surveys.survey_for(name, POINT).code, code)

    def test_sample_lines(self):
        for name, code in SAMPLE_LINES.items():
            with self.subTest(name=name):
                self.assertEqual(surveys.survey_for(name, POLYLINE).code, code)

    def test_every_prefix(self):
        cases = {"SW1": "SW", "VSS1": "VSS", "T1": "T", "P1": "BP", "BP1": "BP",
                 "GW1": "GW", "C1": "C", "N1": "N"}
        for name, code in cases.items():
            with self.subTest(name=name):
                self.assertEqual(surveys.survey_for(name, POINT).code, code)

    def test_case_does_not_matter(self):
        self.assertEqual(surveys.survey_for("sw3", POINT).code, "SW")
        self.assertEqual(surveys.survey_for("Vss 2", POLYLINE).code, "VSS_LINES")

    def test_longer_prefixes_are_not_cut_short(self):
        # SW is sea water, not S; VSS is snorkeling, not V; GW is not G.
        self.assertEqual(surveys.survey_for("SW1", POINT).code, "SW")
        self.assertIsNone(surveys.survey_for("S1", POINT))
        self.assertIsNone(surveys.survey_for("V1", POINT))
        self.assertIsNone(surveys.survey_for("G1", POINT))

    def test_other_features_are_left_out(self):
        for name in ("jetty 4", "beach club", "Works", "MT1", "Noise 1", "12", ""):
            with self.subTest(name=name):
                self.assertIsNone(surveys.survey_for(name, POINT))

    def test_vss_and_transect_lines_come_from_the_kmz(self):
        self.assertEqual(surveys.survey_for("VSS1", POLYLINE).code, "VSS_LINES")
        self.assertEqual(surveys.survey_for("T201 S 2m", POLYLINE).code, "T_LINES")
        self.assertEqual(surveys.survey_for("t3", POLYLINE).code, "T_LINES")
        for name in ("SW1", "P1", "C201 start", "jetty 4", "Track 1", "Transect 1"):
            with self.subTest(name=name):
                self.assertIsNone(surveys.survey_for(name, POLYLINE))

    def test_unknown_geometry(self):
        self.assertIsNone(surveys.survey_for("SW1", "POLYGON"))
        self.assertIsNone(surveys.survey_for("1", "POLYGON", "VSS"))

    def test_lines_named_by_their_folder(self):
        # From SURVEYED - Vilureef Add 2 - 10 2026.kmz: the VSS lines are
        # named 1 to 5 and sit in a folder named VSS.
        for name in ("1", "5", "", "Line 2", "Track 1", "SW1"):
            with self.subTest(name=name):
                self.assertEqual(surveys.survey_for(name, POLYLINE, "VSS").code, "VSS_LINES")
        self.assertEqual(surveys.survey_for("3", POLYLINE, "vss lines").code, "VSS_LINES")
        self.assertEqual(surveys.survey_for("3", POLYLINE, "T").code, "T_LINES")

    def test_line_names_come_before_folders(self):
        self.assertEqual(surveys.survey_for("T1", POLYLINE, "VSS").code, "T_LINES")
        self.assertEqual(surveys.survey_for("VSS2", POLYLINE, "Transects").code, "VSS_LINES")

    def test_other_folders_leave_lines_out(self):
        for folder in ("works", "Addendum 2 - 10 2026", "Transects", "SW (probe+500mlPET)",
                       "currents", "Survey.kmz", "", None):
            with self.subTest(folder=folder):
                self.assertIsNone(surveys.survey_for("1", POLYLINE, folder))

    def test_points_go_by_their_own_names(self):
        self.assertIsNone(surveys.survey_for("1", POINT, "VSS"))
        self.assertEqual(surveys.survey_for("VSS301", POINT, "Transects").code, "VSS")

    def test_folder_name(self):
        cases = {
            "SURVEYED - Vilureef Add 2 - 10 2026.kmz/SURVEYED - Vilureef Add 2 - 10 2026/VSS":
                "VSS",
            "/SURVEYED - Vilureef/SW (probe+500mlPET)": "SW (probe+500mlPET)",
            "Survey.kmz\\Survey\\Transects": "Transects",
            "Survey.kmz/Survey/VSS/": "VSS",
            " Survey.kmz / VSS lines ": "VSS lines",
            "Survey.kmz": "Survey.kmz",
            "": None,
            "/": None,
            None: None,
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(surveys.folder_name(path), expected)


class TransectLineTests(unittest.TestCase):
    def test_feature_id(self):
        cases = {
            "T201 S 2m": "T201", "t 201 line": "T201", "T01": "T1", "T0": "T0",
            "T1-line": "T1", "VSS01": "VSS1", "jetty": None, "12": None, "": None,
            None: None,
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(surveys.feature_id(name), expected)

    def test_points_with_lines_by_id(self):
        points = [("T1 2m N", (0, 0)), ("T2 3.5m NW", (500, 0)), ("T03 3.5m N", (900, 0))]
        lines = [("T1", [(300, 300), (300, 350)]), ("T3 line", [(-500, -500), (-500, -450)])]
        self.assertEqual(surveys.points_with_lines(points, lines, 10), {0, 2})

    def test_points_with_lines_by_place(self):
        points = [("T1 2m N", (0, 0)), ("T2 3.5m NW", (500, 0)), ("T3 3.5m N", (900, 0))]
        # Named differently, but one starts 6 m from T1 and one ends 8 m from T3.
        lines = [("T7", [(6, 0), (6, 50)]), ("T8", [(900, 60), (900, 8)])]
        self.assertEqual(surveys.points_with_lines(points, lines, 10), {0, 2})

    def test_points_far_from_lines_have_none(self):
        points = [("T1 2m N", (0, 0))]
        # The middle of this line passes the point, but neither end is near it.
        lines = [("T5", [(-100, 1), (100, 1)])]
        self.assertEqual(surveys.points_with_lines(points, lines, 10), set())

    def test_no_lines(self):
        self.assertEqual(surveys.points_with_lines([("T1 N", (0, 0))], [], 10), set())


class HelperTests(unittest.TestCase):
    def test_normalise(self):
        self.assertEqual(
            surveys.normalise("  Sea  Water Sampling\tPoints "),
            "sea water sampling points",
        )
        self.assertEqual(surveys.normalise(None), "")
        self.assertEqual(surveys.normalise("SW TABLE"), surveys.normalise("sw table"))

    def test_old_spelling_still_matches(self):
        # Masters made before spell it "Snorkelling".
        for survey in (surveys.by_code("VSS"), surveys.by_code("VSS_LINES")):
            old = survey.layer_name.replace("Snorkeling", "Snorkelling")
            self.assertNotEqual(old, survey.layer_name)
            self.assertEqual(surveys.normalise(old), surveys.normalise(survey.layer_name))

    def test_fix_spelling(self):
        self.assertEqual(
            surveys.fix_spelling("Visual Snorkelling Survey Points"),
            "Visual Snorkeling Survey Points",
        )
        self.assertEqual(surveys.fix_spelling("VISUAL SNORKELLING"), "VISUAL SNORKELING")
        self.assertEqual(surveys.fix_spelling("visual snorkelling"), "visual snorkeling")
        self.assertEqual(
            surveys.fix_spelling("Snorkelling and snorkelling"), "Snorkeling and snorkeling"
        )

    def test_fix_spelling_leaves_the_rest_alone(self):
        for text in ("Visual Snorkeling Survey Lines", "Sea Water Sampling Points", "SW Table", ""):
            self.assertEqual(surveys.fix_spelling(text), text)
        self.assertEqual(surveys.fix_spelling(None), "")

    def test_layer_names_are_spelled_right(self):
        for survey in surveys.SURVEYS:
            self.assertEqual(surveys.fix_spelling(survey.layer_name), survey.layer_name)

    def test_natural_key(self):
        names = ["P10", "P2", "P1", "p3", "SW201", "C202 end", "C201 start", "C201 end"]
        self.assertEqual(
            sorted(names, key=surveys.natural_key),
            ["C201 end", "C201 start", "C202 end", "P1", "P2", "p3", "P10", "SW201"],
        )

    def test_natural_key_handles_empty_names(self):
        self.assertEqual(sorted(["T2", "", None, "T1"], key=surveys.natural_key)[2:],
                         ["T1", "T2"])

    def test_gdb_name_for(self):
        cases = {
            "Masterplan changes surveyed 2.kmz": "Masterplan_changes_surveyed_2",
            "C:/Surveys/Site-A (v2).kml": "Site_A_v2",
            "2026 survey.kmz": "Survey_2026_survey",
            "!!!.kmz": "Survey_Data",
            "survey_points.kmz": "survey_points",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                name = surveys.gdb_name_for(path)
                self.assertEqual(name, expected)
                self.assertRegex(name, r"^[A-Za-z][A-Za-z0-9_]*$")

    def test_utm_wkid(self):
        self.assertEqual(surveys.utm_wkid(3.85), surveys.UTM_NORTH_WKID)
        self.assertEqual(surveys.utm_wkid(0.0), surveys.UTM_NORTH_WKID)
        self.assertEqual(surveys.utm_wkid(-0.6), surveys.UTM_SOUTH_WKID)
        self.assertEqual((surveys.UTM_NORTH_WKID, surveys.UTM_SOUTH_WKID), (32643, 32743))

    def test_unknown_feature_class(self):
        name = surveys.unknown_feature_class("MT")
        self.assertEqual(name, "MT_Points")
        self.assertNotIn(name, [s.feature_class for s in surveys.SURVEYS])

    def test_plural(self):
        self.assertEqual(surveys.plural(1, "point"), "1 point")
        self.assertEqual(surveys.plural(0, "line"), "0 lines")
        self.assertEqual(surveys.plural(7, "transect line"), "7 transect lines")

    def test_error_is_an_exception(self):
        self.assertTrue(issubclass(surveys.SurveyMapError, Exception))

    def test_layout_names_have_no_stray_spaces(self):
        names = [surveys.TABLES_PANEL_NAME]
        for survey in surveys.SURVEYS:
            names.append(survey.layer_name)
            if survey.is_point:
                names += [survey.table_name, survey.heading_name]
        for name in names:
            self.assertEqual(name, " ".join(name.split()))
            self.assertFalse(re.search(r"[\\/:*?\"<>|]", name), name)


if __name__ == "__main__":
    unittest.main()
