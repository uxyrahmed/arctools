# -*- coding: utf-8 -*-
"""Tools that turn the field device's currents CSV into a currents map.

See README.md in this folder for the workflow and every parameter.
"""

import importlib
import os
import sys

import arcpy

# ArcGIS Pro keeps Python running between tool runs, so the currentsmap
# package from an earlier load can still be in memory. Drop it and load the
# package next to this file, fresh, so a new copy of the toolbox works as soon
# as the toolbox is refreshed.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [path for path in sys.path if os.path.normcase(path) != os.path.normcase(_HERE)]
sys.path.insert(0, _HERE)
for _name in [name for name in sys.modules if name.split(".")[0] == "currentsmap"]:
    del sys.modules[_name]
importlib.invalidate_caches()
try:
    from currentsmap import arrows, common, gis, maps  # noqa: E402
except ImportError as error:
    raise ImportError(
        f"{error}. The currentsmap folder next to this toolbox needs all of its "
        "files. Unzip the whole toolbox again into an empty folder, then "
        "restart ArcGIS Pro."
    ) from error


class Toolbox:
    def __init__(self):
        self.label = "Currents Map"
        self.alias = "currentsmap"
        self.tools = [MakeCurrentsMap, DrawCurrentArrows, AddCurrentsToMap]


# ---------------------------------------------------------------------------
# Shared parameter helpers
# ---------------------------------------------------------------------------


def _csv_parameter():
    param = arcpy.Parameter(
        displayName="Currents CSV",
        name="currents_csv",
        datatype="DEFile",
        parameterType="Required",
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


def _coordinate_system_parameter():
    return arcpy.Parameter(
        displayName="Coordinate System to Measure In",
        name="coordinate_system",
        datatype="GPCoordinateSystem",
        parameterType="Optional",
        direction="Input",
    )


def _gdb_parameter():
    param = arcpy.Parameter(
        displayName="Currents Geodatabase",
        name="currents_gdb",
        datatype="DEWorkspace",
        parameterType="Required",
        direction="Input",
    )
    param.filter.list = ["Local Database"]
    return param


def _map_parameter():
    param = arcpy.Parameter(
        displayName="Map",
        name="map",
        datatype="GPString",
        parameterType="Required",
        direction="Input",
    )
    names, default = maps.map_choices()
    if names:
        param.filter.type = "ValueList"
        param.filter.list = names
    if default:
        param.value = default
    return param


def _show_points_parameter():
    param = arcpy.Parameter(
        displayName="Show Start and End Points",
        name="show_points",
        datatype="GPBoolean",
        parameterType="Optional",
        direction="Input",
    )
    param.value = False
    return param


def _zoom_parameter():
    param = arcpy.Parameter(
        displayName="Zoom to Currents",
        name="zoom",
        datatype="GPBoolean",
        parameterType="Optional",
        direction="Input",
    )
    param.value = True
    return param


def _derived_gdb_parameter():
    return arcpy.Parameter(
        displayName="Currents Geodatabase",
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
    """The coordinate system chosen in param, or None to use the default."""
    try:
        try:
            return gis.to_spatial_reference(param.value)
        except Exception:
            return gis.to_spatial_reference(param.valueAsText)
    except Exception as error:
        gis.report(error, f"use the coordinate system in '{param.displayName}'",
                   so="the default is used")
        return None


def _follow_csv(csv_param, name_param):
    """Name the geodatabase after the CSV whenever a new CSV is chosen."""
    if csv_param.altered and not csv_param.hasBeenValidated and csv_param.valueAsText:
        name_param.value = common.gdb_name_for(csv_param.valueAsText)


def _check_gdb_name(param):
    name = (param.valueAsText or "").strip()
    if name.lower().endswith(".gdb"):
        name = name[:-4]
    if name and (not name[0].isalpha() or not name.replace("_", "").isalnum()):
        param.setErrorMessage(
            "Use letters, numbers and underscores only, starting with a letter."
        )


def _check_map(param):
    if not param.filter.list and not param.valueAsText:
        param.setErrorMessage("This project has no maps. Add a map first (Insert > New Map).")


def _check_gdb(param):
    path = param.valueAsText or ""
    if path and not path.lower().endswith(".gdb"):
        param.setErrorMessage("Choose the file geodatabase (.gdb) that Step 1 wrote to.")


def _flag(param):
    return bool(param.value) if param.value is not None else False


def _run(function, *args):
    """Run one step. Returns (True, result), or (False, None) after an error
    message saying what went wrong."""
    try:
        return True, function(*args)
    except Exception as error:
        gis.report(error, warning=False)
        return False, None


class _ToolRun:
    """Wraps a tool's execute: keeps the data the tools make off the map
    until Step 2 adds it, and reports anything unexpected as an error message
    instead of a Python traceback."""

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
# Make Currents Map (all in one)
# ---------------------------------------------------------------------------


class MakeCurrentsMap:
    def __init__(self):
        self.label = "Make Currents Map (All in One)"
        self.description = (
            "Runs Steps 1 and 2 in order: draws an arrow for each current in "
            "the currents CSV, labelled with its speed and direction, then "
            "shows the arrows on the map and zooms to them.")
        self.category = None

    def getParameterInfo(self):
        return [
            _csv_parameter(),
            _map_parameter(),
            _folder_parameter(),
            _gdb_name_parameter(),
            _coordinate_system_parameter(),
            _show_points_parameter(),
            _zoom_parameter(),
            _derived_gdb_parameter(),
        ]

    def updateParameters(self, parameters):
        p = _by_name(parameters)
        _follow_csv(p["currents_csv"], p["gdb_name"])

    def updateMessages(self, parameters):
        p = _by_name(parameters)
        _check_gdb_name(p["gdb_name"])
        _check_map(p["map"])

    def execute(self, parameters, messages):
        with _ToolRun():
            p = _by_name(parameters)
            arcpy.AddMessage("Step 1: Draw Current Arrows")
            ok, gdb = _run(
                arrows.make_geodatabase, p["out_folder"].valueAsText, p["gdb_name"].valueAsText
            )
            if not ok:
                return
            ok, _ = _run(
                arrows.draw_current_arrows,
                p["currents_csv"].valueAsText, gdb, _spatial_reference(p["coordinate_system"]),
            )
            _set_output(parameters, "out_gdb", gdb)
            if not ok:
                return
            arcpy.AddMessage("Step 2: Add Currents to Map")
            _run(
                maps.add_to_map, gdb, p["map"].valueAsText,
                _flag(p["show_points"]), _flag(p["zoom"]),
            )


# ---------------------------------------------------------------------------
# Step 1: Draw Current Arrows
# ---------------------------------------------------------------------------


class DrawCurrentArrows:
    def __init__(self):
        self.label = "Step 1 Draw Current Arrows"
        self.description = (
            "Works out each current's speed and direction from the currents "
            "CSV (each current's start and end point and the time each was "
            "recorded) and saves an arrow from start to end, labelled like "
            "'0.21 m/s S', to C_Arrows, and the start and end points to "
            "C_Points, in a file geodatabase. The geodatabase is made if it "
            "isn't there yet.")
        self.category = None

    def getParameterInfo(self):
        return [
            _csv_parameter(),
            _folder_parameter(),
            _gdb_name_parameter(),
            _coordinate_system_parameter(),
            _derived_gdb_parameter(),
        ]

    def updateParameters(self, parameters):
        p = _by_name(parameters)
        _follow_csv(p["currents_csv"], p["gdb_name"])

    def updateMessages(self, parameters):
        _check_gdb_name(_by_name(parameters)["gdb_name"])

    def execute(self, parameters, messages):
        with _ToolRun():
            p = _by_name(parameters)
            ok, gdb = _run(
                arrows.make_geodatabase, p["out_folder"].valueAsText, p["gdb_name"].valueAsText
            )
            if not ok:
                return
            ok, _ = _run(
                arrows.draw_current_arrows,
                p["currents_csv"].valueAsText, gdb, _spatial_reference(p["coordinate_system"]),
            )
            if ok:
                _set_output(parameters, "out_gdb", gdb)


# ---------------------------------------------------------------------------
# Step 2: Add Currents to Map
# ---------------------------------------------------------------------------


class AddCurrentsToMap:
    def __init__(self):
        self.label = "Step 2 Add Currents to Map"
        self.description = (
            "Shows the current arrows from the geodatabase on a map as a "
            "layer called Currents, labelled with each current's speed and "
            "direction, and zooms to them. A Currents layer already in the "
            "map is pointed at the new data and keeps its style.")
        self.category = None

    def getParameterInfo(self):
        return [_gdb_parameter(), _map_parameter(), _show_points_parameter(), _zoom_parameter()]

    def updateMessages(self, parameters):
        p = _by_name(parameters)
        _check_gdb(p["currents_gdb"])
        _check_map(p["map"])

    def execute(self, parameters, messages):
        with _ToolRun():
            p = _by_name(parameters)
            _run(
                maps.add_to_map, p["currents_gdb"].valueAsText, p["map"].valueAsText,
                _flag(p["show_points"]), _flag(p["zoom"]),
            )
