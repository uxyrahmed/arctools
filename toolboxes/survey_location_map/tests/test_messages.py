# -*- coding: utf-8 -*-
"""Tests for surveymap.messages. Run from the repository root with:

    python -m unittest discover -s toolboxes/survey_location_map/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from surveymap import messages  # noqa: E402
from surveymap.surveys import SurveyMapError  # noqa: E402

# The error from the first run in ArcGIS Pro, deleting the converted KMZ.
DELETE_ERROR = (
    "ERROR 000601: Cannot delete C:\\Users\\CDE\\OneDrive - CDE Consulting\\Documents"
    "\\ArcGIS\\Projects\\R. Ungoofaaru\\scratch\\kmz_b110d7434a85.gdb.  May be locked "
    "by another application.\nFailed to execute (Delete).\n"
)
SCHEMA_LOCK_ERROR = (
    "ERROR 000464: Cannot get exclusive schema lock.  Either being edited or in use "
    "by another application or service.\nFailed to execute (AddField).\n"
)
MISSING_ERROR = (
    "Failed to execute. Parameters are not valid.\nERROR 000732: Input Features: "
    "Dataset C:\\data\\gone.gdb\\SW_Points does not exist or is not supported\n"
    "Failed to execute (CalculateGeometryAttributes).\n"
)


class ExecuteError(RuntimeError):
    """Stands in for arcpy.ExecuteError, which ArcGIS tools raise."""


class LockTests(unittest.TestCase):
    def test_lock_errors(self):
        for text in (
            DELETE_ERROR,
            SCHEMA_LOCK_ERROR,
            "Cannot acquire a lock.",
            "[WinError 32] The process cannot access the file because it is being "
            "used by another process: 'a00000004.gdbtable'",
            "Workspace or data source is locked.",
        ):
            with self.subTest(text=text):
                self.assertTrue(messages.is_lock_error(RuntimeError(text)))

    def test_other_errors(self):
        for text in (MISSING_ERROR, "Couldn't place the block of text", "Unblocked", ""):
            with self.subTest(text=text):
                self.assertFalse(messages.is_lock_error(RuntimeError(text)))


class ErrorTextTests(unittest.TestCase):
    def test_failed_to_execute_lines_go(self):
        text = messages.error_text(ExecuteError(MISSING_ERROR))
        self.assertTrue(text.startswith("ERROR 000732: Input Features: Dataset"))
        self.assertNotIn("Failed to execute", text)
        self.assertNotIn("\n", text)

    def test_lock_errors_say_what_to_do(self):
        text = messages.error_text(ExecuteError(DELETE_ERROR))
        self.assertTrue(text.startswith("ERROR 000601: Cannot delete"))
        self.assertTrue(text.endswith(messages.LOCK_HINT))
        self.assertEqual(text.count(messages.LOCK_HINT), 1)

    def test_python_errors_keep_their_type(self):
        error = AttributeError("'NoneType' object has no attribute 'symbol'")
        self.assertEqual(
            messages.error_text(error),
            "AttributeError: 'NoneType' object has no attribute 'symbol'",
        )
        self.assertEqual(messages.error_text(KeyError()), "KeyError")

    def test_arcgis_errors_raised_as_runtime_errors(self):
        # Some arcpy functions raise RuntimeError with an ArcGIS error code.
        text = messages.error_text(RuntimeError("ERROR 999999: Something failed."))
        self.assertEqual(text, "ERROR 999999: Something failed.")

    def test_survey_map_errors_are_kept_as_they_are(self):
        error = SurveyMapError("Couldn't write SW_Points. Cannot acquire a lock.")
        self.assertEqual(messages.error_text(error), str(error))


class ProblemTests(unittest.TestCase):
    def test_what_and_reason(self):
        self.assertEqual(
            messages.problem(ExecuteError("ERROR 999999: Oops.\nFailed to execute (X)."),
                             "update the legend"),
            "Couldn't update the legend. ERROR 999999: Oops.",
        )

    def test_what_happens_instead(self):
        self.assertEqual(
            messages.problem(ExecuteError("ERROR 999999: Oops."),
                             "work out X and Y for SW_Points", so="they're left empty"),
            "Couldn't work out X and Y for SW_Points, so they're left empty. "
            "ERROR 999999: Oops.",
        )

    def test_survey_map_error_is_used_as_it_is(self):
        error = SurveyMapError("The KMZ layer Points has no Name field.")
        self.assertEqual(messages.problem(error, "read Points from the KMZ"), str(error))
        self.assertEqual(
            messages.problem(error, "read Points from the KMZ", so="its features are left out"),
            "The KMZ layer Points has no Name field. Its features are left out.",
        )

    def test_without_what(self):
        self.assertEqual(messages.problem(ValueError("bad")), "ValueError: bad")


class DetailsTests(unittest.TestCase):
    def test_bugs_get_details(self):
        self.assertTrue(messages.needs_details(AttributeError("x")))
        self.assertTrue(messages.needs_details(KeyError("SW")))

    def test_data_problems_dont(self):
        self.assertFalse(messages.needs_details(SurveyMapError("No survey points.")))
        self.assertFalse(messages.needs_details(ExecuteError(MISSING_ERROR)))
        self.assertFalse(messages.needs_details(RuntimeError("Cannot acquire a lock.")))


if __name__ == "__main__":
    unittest.main()
