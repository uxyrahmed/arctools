# -*- coding: utf-8 -*-
"""Tools that turn a survey KMZ into a Survey Location Map.

See README.md in this folder for the workflow, every parameter and the names
the master layout needs.
"""

import importlib
import os
import sys

import arcpy

# ArcGIS Pro keeps Python running between tool runs, so the surveymap package
# from an earlier load can still be in memory: an older copy, or one from
# another folder. Drop it and load the package next to this file, fresh, so
# a new copy of the toolbox works as soon as the toolbox is refreshed.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [path for path in sys.path if os.path.normcase(path) != os.path.normcase(_HERE)]
sys.path.insert(0, _HERE)
for _name in [name for name in sys.modules if name.split(".")[0] == "surveymap"]:
    del sys.modules[_name]
importlib.invalidate_caches()
try:
    from surveymap import (  # noqa: E402
        arrows, currents, directions, gis, kmz, layouts, messages, stacking, surveys,
        transects,
    )
except ImportError as error:
    raise ImportError(
        f"{error}. The surveymap folder next to this toolbox needs all of its "
        "files. Unzip the whole toolbox again into an empty folder, then "
        "restart ArcGIS Pro."
    ) from error

SPREAD_EVENLY = "Spread evenly"
STACK_FROM_TOP = "Stack from top"


class Toolbox:
    def __init__(self):
        self.label = "Survey Location Map"
        self.alias = "surveymap"
        self.tools = [
            MakeSurveyMap,
            ImportSurveyKmz,
            DrawTransectLines,
            DrawCurrentArrows,
            ConnectDataToLayout,
            RestyleLayout,
        ]


# ---------------------------------------------------------------------------
# Shared parameter helpers
# ---------------------------------------------------------------------------


def _kmz_parameter():
    param = arcpy.Parameter(
        displayName="Survey KMZ",
        name="in_kmz",
        datatype="DEFile",
        parameterType="Required",
        direction="Input",
    )
    param.filter.list = ["kmz", "kml"]
    return param


def _csv_parameter(required):
    param = arcpy.Parameter(
        displayName="Currents CSV",
        name="currents_csv",
        datatype="DEFile",
        parameterType="Required" if required else "Optional",
        direction="Input",
    )
    param.filter.list = ["csv", "txt"]
    return param


def _folder_parameter():
    param = arcpy.Parameter(
        displayName="Output Folder",
        name="out_folder",
        datatype="DEFolder",
        parameterType="Required",
        direction="Input",
    )
    try:
        param.value = arcpy.mp.ArcGISProject("CURRENT").homeFolder
    except Exception:
        pass
    return param


def _gdb_name_parameter():
    return arcpy.Parameter(
        displayName="Geodatabase Name",
        name="gdb_name",
        datatype="GPString",
        parameterType="Required",
        direction="Input",
    )


def _coordinate_system_parameter(display_name):
    return arcpy.Parameter(
        displayName=display_name,
        name="coordinate_system",
        datatype="GPCoordinateSystem",
        parameterType="Optional",
        direction="Input",
    )


def _length_parameter():
    param = arcpy.Parameter(
        displayName="Transect Line Length (metres)",
        name="line_length",
        datatype="GPDouble",
        parameterType="Required",
        direction="Input",
    )
    param.value = surveys.TRANSECT_LENGTH_M
    return param


def _layout_parameter():
    param = arcpy.Parameter(
        displayName="Layout",
        name="layout",
        datatype="GPString",
        parameterType="Required",
        direction="Input",
    )
    names, default = layouts.layout_choices()
    if names:
        param.filter.type = "ValueList"
        param.filter.list = names
    if default:
        param.value = default
    return param


def _survey_gdb_parameter():
    param = arcpy.Parameter(
        displayName="Survey Geodatabase",
        name="survey_gdb",
        datatype="DEWorkspace",
        parameterType="Required",
        direction="Input",
    )
    param.filter.list = ["Local Database"]
    return param


def _spacing_parameter():
    param = arcpy.Parameter(
        displayName="Table Spacing",
        name="spacing",
        datatype="GPString",
        parameterType="Required",
        direction="Input",
    )
    param.filter.type = "ValueList"
    param.filter.list = [STACK_FROM_TOP, SPREAD_EVENLY]
    param.value = STACK_FROM_TOP
    return param


def _derived_gdb_parameter():
    return arcpy.Parameter(
        displayName="Survey Geodatabase",
        name="out_gdb",
        datatype="DEWorkspace",
        parameterType="Derived",
        direction="Output",
    )


def _by_name(parameters):
    return {param.name: param for param in parameters}


def _set_output(parameters, name, value):
    try:
        names = [param.name for param in parameters]
        arcpy.SetParameterAsText(names.index(name), value)
    except Exception:
        pass  # It only fills in the output parameter; the work is done.


def _spatial_reference(param):
    """The coordinate system chosen in param, or None to use the default. One
    that can't be read gives a warning and the default."""
    try:
        try:
            return gis.to_spatial_reference(param.value)
        except Exception:
            return gis.to_spatial_reference(param.valueAsText)
    except Exception as error:
        gis.report(error, f"use the coordinate system in '{param.displayName}'",
                   so="the default is used")
        return None


def _follow_kmz(kmz_param, name_param):
    """Name the geodatabase after the KMZ whenever a new KMZ is chosen."""
    if kmz_param.altered and not kmz_param.hasBeenValidated and kmz_param.valueAsText:
        name_param.value = surveys.gdb_name_for(kmz_param.valueAsText)


def _check_gdb_name(param):
    name = (param.valueAsText or "").strip()
    if name.lower().endswith(".gdb"):
        name = name[:-4]
    if name and (not name[0].isalpha() or not name.replace("_", "").isalnum()):
        param.setErrorMessage(
            "Use letters, numbers and underscores only, starting with a letter."
        )


def _check_positive(param, what):
    if param.value is not None and param.value <= 0:
        param.setErrorMessage(f"{what} must be more than 0.")


def _check_layout(param):
    if not param.filter.list and not param.valueAsText:
        param.setErrorMessage(
            "This project has no layouts. Import the master Survey Location Map "
            "layout first (Insert > Import Layout)."
        )


def _check_survey_gdb(param):
    path = param.valueAsText or ""
    if path and not path.lower().endswith(".gdb"):
        param.setErrorMessage("Choose the file geodatabase (.gdb) that Step 1 made.")


def _run(function, *args, carry_on=False):
    """Run one step. Returns (True, result), or (False, None) if it failed.

    The problem is reported as an error, or as a warning when carry_on is True
    and the tool keeps going without this step. Either way it's a message
    saying what went wrong, not a Python traceback.
    """
    try:
        return True, function(*args)
    except Exception as error:
        gis.report(error, warning=carry_on)
        return False, None


class _ToolRun:
    """Wraps a tool's execute: keeps the data the tools make along the way off
    the map, and reports anything unexpected as an error message instead of a
    Python traceback."""

    def __enter__(self):
        self._outputs = gis.outputs_off_map().__enter__()
        return self

    def __exit__(self, kind, error, tb):
        self._outputs.__exit__(kind, error, tb)
        if error is None or not isinstance(error, Exception):
            return False
        gis.report(error, warning=False)
        return True


# ---------------------------------------------------------------------------
# Make Survey Map (all in one)
# ---------------------------------------------------------------------------


class MakeSurveyMap:
    def __init__(self):
        self.label = "Make Survey Map (All in One)"
        self.description = (
            "Runs Steps 1 to 5 in order: imports the survey KMZ, draws the "
            "transect lines, draws the current arrows if you give a currents "
            "CSV, connects the data to the master layout and restyles the "
            "layout to fit the surveys in the KMZ.")
        self.category = None

    def getParameterInfo(self):
        return [
            _kmz_parameter(),
            _csv_parameter(required=False),
            _layout_parameter(),
            _folder_parameter(),
            _gdb_name_parameter(),
            _coordinate_system_parameter("Coordinate System for X and Y"),
            _length_parameter(),
            _spacing_parameter(),
            _derived_gdb_parameter(),
        ]

    def updateParameters(self, parameters):
        p = _by_name(parameters)
        _follow_kmz(p["in_kmz"], p["gdb_name"])

    def updateMessages(self, parameters):
        p = _by_name(parameters)
        _check_gdb_name(p["gdb_name"])
        _check_positive(p["line_length"], "The line length")
        _check_layout(p["layout"])

    def execute(self, parameters, messages):
        with _ToolRun():
            self._make_map(parameters)

    def _make_map(self, parameters):
        """Steps 1 to 5. A problem with one survey, layer or table is a warning
        and the rest carry on. The tool only stops if Step 1 or Step 4 can't
        do anything at all; if Step 2, 3 or 5 fails, the rest still runs."""
        p = _by_name(parameters)
        coordinate_system = _spatial_reference(p["coordinate_system"])
        layout_name = p["layout"].valueAsText
        spread = p["spacing"].valueAsText == SPREAD_EVENLY

        arcpy.AddMessage("Step 1 of 5: Import Survey KMZ")
        ok, result = _run(
            kmz.import_kmz,
            p["in_kmz"].valueAsText,
            p["out_folder"].valueAsText,
            p["gdb_name"].valueAsText,
            coordinate_system,
        )
        if not ok:
            return
        # Only what this run wrote goes on the map, never data left from an
        # earlier run that couldn't be replaced.
        gdb, present = result
        _set_output(parameters, "out_gdb", gdb)

        arcpy.AddMessage("Step 2 of 5: Draw Transect Lines")
        if surveys.TRANSECT_POINTS in present:
            ok, lines = _run(
                transects.draw_transect_lines,
                os.path.join(gdb, surveys.by_code(surveys.TRANSECT_POINTS).feature_class),
                os.path.join(gdb, surveys.by_code(surveys.TRANSECT_LINES).feature_class),
                p["line_length"].value,
                coordinate_system,
                carry_on=True,
            )
            if not ok:
                arcpy.AddMessage(
                    "Carried on without transect lines. Once the problem above is "
                    "fixed, run Step 2 Draw Transect Lines on its own."
                )
            elif lines:
                present[surveys.TRANSECT_LINES] = lines
        else:
            arcpy.AddMessage("No transect points to draw lines from.")

        arcpy.AddMessage("Step 3 of 5: Draw Current Arrows")
        csv_path = p["currents_csv"].valueAsText
        if csv_path:
            ok, drawn = _run(
                arrows.draw_current_arrows, csv_path, gdb, coordinate_system, carry_on=True
            )
            if ok and drawn:
                present[surveys.CURRENT_ARROWS] = drawn
            else:
                arcpy.AddMessage(
                    "Carried on without current arrows, so the currents show as "
                    "points. Once the problem above is fixed, run Step 3 Draw "
                    "Current Arrows, then Steps 4 and 5, on their own."
                )
        elif surveys.CURRENT_POINTS in present:
            arcpy.AddMessage("No currents CSV, so the currents show as points.")
        else:
            arcpy.AddMessage("No currents CSV, so no current arrows.")

        arcpy.AddMessage("Step 4 of 5: Connect Data to Layout")
        ok, present = _run(layouts.connect_data, layout_name, gdb, present)
        if not ok:
            return

        arcpy.AddMessage("Step 5 of 5: Restyle Layout")
        ok, _ = _run(layouts.restyle_layout, layout_name, gdb, spread, present)
        if not ok:
            arcpy.AddMessage(
                "Steps 1 to 4 finished, so the survey data is on the map. Once the "
                "problem above is fixed, run Step 5 Restyle Layout on its own."
            )


# ---------------------------------------------------------------------------
# Step 1: Import Survey KMZ
# ---------------------------------------------------------------------------


class ImportSurveyKmz:
    def __init__(self):
        self.label = "Step 1 Import Survey KMZ"
        self.description = (
            "Converts a survey KMZ and splits its features by name prefix into "
            "one feature class per survey (SW_Points, VSS_Points, T_Points, "
            "BP_Points, GW_Points, C_Points, N_Points and VSS_Lines). Points "
            "keep Name, X and Y; lines keep Name. Everything else in the KMZ "
            "is left out.")
        self.category = None

    def getParameterInfo(self):
        # The geodatabase is the only output, so the survey feature classes
        # aren't added to the map next to the master layout's own layers.
        return [
            _kmz_parameter(),
            _folder_parameter(),
            _gdb_name_parameter(),
            _coordinate_system_parameter("Coordinate System for X and Y"),
            _derived_gdb_parameter(),
        ]

    def updateParameters(self, parameters):
        p = _by_name(parameters)
        _follow_kmz(p["in_kmz"], p["gdb_name"])

    def updateMessages(self, parameters):
        _check_gdb_name(_by_name(parameters)["gdb_name"])

    def execute(self, parameters, messages):
        with _ToolRun():
            p = _by_name(parameters)
            ok, result = _run(
                kmz.import_kmz,
                p["in_kmz"].valueAsText,
                p["out_folder"].valueAsText,
                p["gdb_name"].valueAsText,
                _spatial_reference(p["coordinate_system"]),
            )
            if ok:
                _set_output(parameters, "out_gdb", result[0])


# ---------------------------------------------------------------------------
# Step 2: Draw Transect Lines
# ---------------------------------------------------------------------------


class DrawTransectLines:
    def __init__(self):
        self.label = "Step 2 Draw Transect Lines"
        self.description = (
            "Draws a line from each transect point in the compass direction in "
            "its name, for example 'T201 S 2m' goes south. Points with no "
            "direction in their name get no line.")
        self.category = None

    def getParameterInfo(self):
        in_points = arcpy.Parameter(
            displayName="Transect Points",
            name="in_points",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        in_points.filter.list = ["Point"]

        out_lines = arcpy.Parameter(
            displayName="Output Transect Lines",
            name="out_lines",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output",
        )
        return [
            in_points,
            out_lines,
            _length_parameter(),
            _coordinate_system_parameter("Coordinate System to Draw In"),
        ]

    def updateParameters(self, parameters):
        p = _by_name(parameters)
        in_points, out_lines = p["in_points"], p["out_lines"]
        if in_points.altered and not in_points.hasBeenValidated and not out_lines.altered:
            try:
                folder = os.path.dirname(arcpy.Describe(in_points.value).catalogPath)
                name = surveys.by_code(surveys.TRANSECT_LINES).feature_class
                out_lines.value = os.path.join(folder, name)
            except Exception:
                pass

    def updateMessages(self, parameters):
        p = _by_name(parameters)
        _check_positive(p["line_length"], "The line length")
        # The lines are redrawn on every run, so replacing them is expected.
        out_lines = p["out_lines"]
        if out_lines.valueAsText and arcpy.Exists(out_lines.valueAsText):
            out_lines.clearMessage()

    def execute(self, parameters, messages):
        with _ToolRun():
            p = _by_name(parameters)
            _run(
                transects.draw_transect_lines,
                p["in_points"].valueAsText,
                p["out_lines"].valueAsText,
                p["line_length"].value,
                _spatial_reference(p["coordinate_system"]),
            )


# ---------------------------------------------------------------------------
# Step 3: Draw Current Arrows
# ---------------------------------------------------------------------------


class DrawCurrentArrows:
    def __init__(self):
        self.label = "Step 3 Draw Current Arrows"
        self.description = (
            "Works out each current's speed and direction from the currents "
            "CSV (each current's start and end point and the time each was "
            "recorded) and draws an arrow from start to end, labelled with the "
            "speed and direction. Steps 4 and 5 then show the arrows instead of "
            "the current points.")
        self.category = None

    def getParameterInfo(self):
        return [
            _csv_parameter(required=True),
            _survey_gdb_parameter(),
            _coordinate_system_parameter("Coordinate System to Measure In"),
        ]

    def updateMessages(self, parameters):
        _check_survey_gdb(_by_name(parameters)["survey_gdb"])

    def execute(self, parameters, messages):
        with _ToolRun():
            p = _by_name(parameters)
            _run(
                arrows.draw_current_arrows,
                p["currents_csv"].valueAsText,
                p["survey_gdb"].valueAsText,
                _spatial_reference(p["coordinate_system"]),
            )


# ---------------------------------------------------------------------------
# Step 4: Connect Data to Layout
# ---------------------------------------------------------------------------


class ConnectDataToLayout:
    def __init__(self):
        self.label = "Step 4 Connect Data to Layout"
        self.description = (
            "Points each survey layer in the master layout's map at the "
            "matching feature class in the survey geodatabase, links each "
            "survey's table to its layer and labels the points. Surveys with "
            "no data are turned off. Current arrows from Step 3 are added to "
            "the map the first time, and shown instead of the current points.")
        self.category = None

    def getParameterInfo(self):
        return [_layout_parameter(), _survey_gdb_parameter()]

    def updateMessages(self, parameters):
        p = _by_name(parameters)
        _check_layout(p["layout"])
        _check_survey_gdb(p["survey_gdb"])

    def execute(self, parameters, messages):
        with _ToolRun():
            p = _by_name(parameters)
            _run(layouts.connect_data, p["layout"].valueAsText, p["survey_gdb"].valueAsText)


# ---------------------------------------------------------------------------
# Step 5: Restyle Layout
# ---------------------------------------------------------------------------


class RestyleLayout:
    def __init__(self):
        self.label = "Step 5 Restyle Layout"
        self.description = (
            "Hides the layers, tables, headings and legend entries of surveys "
            "that aren't in the survey geodatabase, sizes each table to its "
            "rows and stacks the tables in the Tables Panel rectangle, from "
            "the top or spread evenly down it.")
        self.category = None

    def getParameterInfo(self):
        return [_layout_parameter(), _survey_gdb_parameter(), _spacing_parameter()]

    def updateMessages(self, parameters):
        p = _by_name(parameters)
        _check_layout(p["layout"])
        _check_survey_gdb(p["survey_gdb"])

    def execute(self, parameters, messages):
        with _ToolRun():
            p = _by_name(parameters)
            _run(
                layouts.restyle_layout,
                p["layout"].valueAsText,
                p["survey_gdb"].valueAsText,
                p["spacing"].valueAsText == SPREAD_EVENLY,
            )
