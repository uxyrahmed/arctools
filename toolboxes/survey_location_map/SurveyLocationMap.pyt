# -*- coding: utf-8 -*-
"""Tools that turn a survey KMZ into a Survey Location Map.

See README.md in this folder for the workflow, every parameter and the names
the master layout needs.
"""

import importlib
import os
import sys

import arcpy

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from surveymap import directions, gis, kmz, layouts, stacking, surveys, transects  # noqa: E402

# ArcGIS Pro keeps imported modules loaded between runs. Reload so edits to
# the surveymap package are picked up when the toolbox is refreshed.
for _module in (surveys, directions, stacking, gis, kmz, transects, layouts):
    importlib.reload(_module)

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
    names = [param.name for param in parameters]
    arcpy.SetParameterAsText(names.index(name), value)


def _spatial_reference(param):
    try:
        return gis.to_spatial_reference(param.value)
    except Exception:
        return gis.to_spatial_reference(param.valueAsText)


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


def _run(function, *args, **kwargs):
    """Run a step, turning a SurveyMapError into a tool error message.
    Returns (True, result), or (False, None) if the step failed."""
    try:
        return True, function(*args, **kwargs)
    except surveys.SurveyMapError as error:
        arcpy.AddError(str(error))
        return False, None


# ---------------------------------------------------------------------------
# Make Survey Map (all in one)
# ---------------------------------------------------------------------------


class MakeSurveyMap:
    def __init__(self):
        self.label = "Make Survey Map (All in One)"
        self.description = (
            "Runs Steps 1 to 4 in order: imports the survey KMZ, draws the "
            "transect lines, connects the data to the master layout and "
            "restyles the layout to fit the surveys in the KMZ.")
        self.category = None

    def getParameterInfo(self):
        return [
            _kmz_parameter(),
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
        p = _by_name(parameters)
        coordinate_system = _spatial_reference(p["coordinate_system"])
        layout_name = p["layout"].valueAsText
        spread = p["spacing"].valueAsText == SPREAD_EVENLY

        arcpy.AddMessage("Step 1 of 4: Import Survey KMZ")
        ok, result = _run(
            kmz.import_kmz,
            p["in_kmz"].valueAsText,
            p["out_folder"].valueAsText,
            p["gdb_name"].valueAsText,
            coordinate_system,
        )
        if not ok:
            return
        gdb = result[0]
        _set_output(parameters, "out_gdb", gdb)

        arcpy.AddMessage("Step 2 of 4: Draw Transect Lines")
        transect_points = os.path.join(
            gdb, surveys.by_code(surveys.TRANSECT_POINTS).feature_class)
        transect_lines = os.path.join(
            gdb, surveys.by_code(surveys.TRANSECT_LINES).feature_class)
        if arcpy.Exists(transect_points) and gis.count(transect_points):
            ok, _ = _run(
                transects.draw_transect_lines,
                transect_points,
                transect_lines,
                p["line_length"].value,
                coordinate_system,
            )
            if not ok:
                return
        else:
            arcpy.AddMessage("No transect points in this KMZ, so no lines to draw.")

        arcpy.AddMessage("Step 3 of 4: Connect Data to Layout")
        ok, _ = _run(layouts.connect_data, layout_name, gdb)
        if not ok:
            return

        arcpy.AddMessage("Step 4 of 4: Restyle Layout")
        _run(layouts.restyle_layout, layout_name, gdb, spread)


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
        p = _by_name(parameters)
        _run(
            transects.draw_transect_lines,
            p["in_points"].valueAsText,
            p["out_lines"].valueAsText,
            p["line_length"].value,
            _spatial_reference(p["coordinate_system"]),
        )


# ---------------------------------------------------------------------------
# Step 3: Connect Data to Layout
# ---------------------------------------------------------------------------


class ConnectDataToLayout:
    def __init__(self):
        self.label = "Step 3 Connect Data to Layout"
        self.description = (
            "Points each survey layer in the master layout's map at the "
            "matching feature class in the survey geodatabase, links each "
            "survey's table to its layer and labels the points. Surveys with "
            "no data are turned off.")
        self.category = None

    def getParameterInfo(self):
        return [_layout_parameter(), _survey_gdb_parameter()]

    def updateMessages(self, parameters):
        p = _by_name(parameters)
        _check_layout(p["layout"])
        _check_survey_gdb(p["survey_gdb"])

    def execute(self, parameters, messages):
        p = _by_name(parameters)
        _run(layouts.connect_data, p["layout"].valueAsText, p["survey_gdb"].valueAsText)


# ---------------------------------------------------------------------------
# Step 4: Restyle Layout
# ---------------------------------------------------------------------------


class RestyleLayout:
    def __init__(self):
        self.label = "Step 4 Restyle Layout"
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
        p = _by_name(parameters)
        _run(
            layouts.restyle_layout,
            p["layout"].valueAsText,
            p["survey_gdb"].valueAsText,
            p["spacing"].valueAsText == SPREAD_EVENLY,
        )
