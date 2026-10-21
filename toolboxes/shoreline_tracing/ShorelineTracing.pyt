# -*- coding: utf-8 -*-
"""Tools that learn to trace shorelines from drone images.

See README.md in this folder for the workflow and every parameter.
"""

import csv
import importlib
import os
import sys

import arcpy

# ArcGIS Pro keeps Python running between tool runs, so an older copy of the
# shoreline package can still be in memory. Drop it and load the one next to
# this file, so edits work as soon as the toolbox is refreshed.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [path for path in sys.path if os.path.normcase(path) != os.path.normcase(_HERE)]
sys.path.insert(0, _HERE)
for _name in [name for name in sys.modules if name.split(".")[0] == "shoreline"]:
    del sys.modules[_name]
importlib.invalidate_caches()
try:
    from shoreline import gis, names  # noqa: E402
except ImportError as error:
    raise ImportError(
        f"{error}. The shoreline folder next to this toolbox needs all of its "
        "files. Unzip the whole toolbox again into an empty folder, then "
        "restart ArcGIS Pro."
    ) from error


class Toolbox:
    def __init__(self):
        self.label = "Shoreline Tracing"
        self.alias = "shoreline"
        self.tools = [PrepareTrainingData, TrainShorelineModel, TraceShoreline, CheckAccuracy]


def _value_path(value):
    """A file path for a parameter value, which may be a layer or text."""
    for attribute in ("dataSource", "catalogPath"):
        path = getattr(value, attribute, None)
        if path:
            return str(path)
    try:
        return arcpy.Describe(value).catalogPath
    except Exception:  # noqa: BLE001
        return str(value)


def _needs_image_analyst():
    if arcpy.CheckExtension("ImageAnalyst") != "Available":
        raise arcpy.ExecuteError(
            "These tools need the Image Analyst extension, and it isn't available. "
            "Check Project > Licensing in ArcGIS Pro.")
    arcpy.CheckOutExtension("ImageAnalyst")


def _param(display, name, datatype, required=True, direction="Input", default=None,
           category=None):
    param = arcpy.Parameter(
        displayName=display, name=name, datatype=datatype,
        parameterType="Required" if required else "Optional", direction=direction,
        category=category)
    if default is not None:
        param.value = default
    return param


# ---------------------------------------------------------------------------
# 1. Prepare Training Data
# ---------------------------------------------------------------------------


class PrepareTrainingData:
    def __init__(self):
        self.label = "1. Prepare Training Data"
        self.description = (
            "Turns past surveys (a drone image and its hand-drawn low tide, high tide "
            "and vegetation lines) into training tiles for the model.")

    def getParameterInfo(self):
        surveys = arcpy.Parameter(
            displayName="Surveys", name="surveys", datatype="GPValueTable",
            parameterType="Required", direction="Input")
        surveys.columns = [
            ["GPRasterLayer", "Drone image"],
            ["GPFeatureLayer", "Low tide line (polygons)"],
            ["GPFeatureLayer", "High tide line (lines)"],
            ["GPFeatureLayer", "Vegetation line (polygons)"],
        ]
        out_folder = _param("Output training folder", "out_folder", "DEFolder",
                            direction="Output")
        cell = _param("Tile cell size (m)", "cell_size", "GPDouble",
                      default=names.DEFAULT_CELL_SIZE, category="Advanced")
        tile = _param("Tile size (pixels)", "tile_size", "GPLong", default=256,
                      category="Advanced")
        reach = _param("High tide line reach (m)", "reach", "GPDouble", default=50.0,
                       category="Advanced")
        return [surveys, out_folder, cell, tile, reach]

    def isLicensed(self):
        return True

    def updateMessages(self, parameters):
        if parameters[2].value is not None and parameters[2].value <= 0:
            parameters[2].setErrorMessage("Use a cell size above 0.")
        return

    def execute(self, parameters, messages):
        _needs_image_analyst()
        rows = parameters[0].values or []
        out_folder = parameters[1].valueAsText
        cell = float(parameters[2].value)
        tile = int(parameters[3].value)
        reach = float(parameters[4].value)

        os.makedirs(out_folder, exist_ok=True)
        zones_gdb = os.path.join(out_folder, "zones.gdb")
        if not arcpy.Exists(zones_gdb):
            arcpy.management.CreateFileGDB(out_folder, "zones.gdb")

        surveys = [[_value_path(value) for value in row] for row in rows]
        survey_names = names.unique_names([row[0] for row in surveys])
        done = []
        for (image, low, high, veg), name in zip(surveys, survey_names):
            done.append(gis.prepare_survey(image, low, high, veg, out_folder, zones_gdb,
                                           name, cell, tile, reach, messages))
        names.write_settings(out_folder, {"cell_size": cell, "tile_size": tile,
                                          "surveys": survey_names})
        messages.addMessage(
            f"Done: {len(done)} survey(s). Next, run 2. Train Shoreline Model on {out_folder}.")


# ---------------------------------------------------------------------------
# 2. Train Shoreline Model
# ---------------------------------------------------------------------------


class TrainShorelineModel:
    def __init__(self):
        self.label = "2. Train Shoreline Model"
        self.description = "Trains the model on the tiles from 1. Prepare Training Data."

    def getParameterInfo(self):
        training = _param("Training folder", "training_folder", "DEFolder")
        model = _param("Output model folder", "model_folder", "DEFolder", direction="Output")
        epochs = _param("Maximum epochs", "epochs", "GPLong", default=50)
        batch = _param("Batch size", "batch_size", "GPLong", default=8)
        backbone = _param("Backbone", "backbone", "GPString", default="RESNET34",
                          category="Advanced")
        backbone.filter.list = ["RESNET34", "RESNET50"]
        arguments = _param("Model arguments", "arguments", "GPString", required=False,
                           category="Advanced")
        return [training, model, epochs, batch, backbone, arguments]

    def isLicensed(self):
        return True

    def updateMessages(self, parameters):
        folder = parameters[0].valueAsText
        if folder and os.path.isdir(folder) and not names.training_folders(folder):
            parameters[0].setErrorMessage(
                "No training tiles here. Pick the output folder of 1. Prepare Training Data.")
        return

    def execute(self, parameters, messages):
        _needs_image_analyst()
        training = parameters[0].valueAsText
        model_folder = parameters[1].valueAsText
        folders = names.training_folders(training)
        if not folders:
            raise arcpy.ExecuteError(f"No training tiles in {training}.")
        gis.train(folders, model_folder, int(parameters[2].value), int(parameters[3].value),
                  parameters[4].valueAsText, parameters[5].valueAsText, messages)
        settings = names.read_settings(training)
        if settings:
            names.write_settings(model_folder, settings)
        model = gis.find_model_file(model_folder)
        messages.addMessage(
            f"Saved the model to {model or model_folder}. Next, run 3. Trace Shoreline "
            "on a new drone image, or on a survey you left out to check the accuracy.")


# ---------------------------------------------------------------------------
# 3. Trace Shoreline
# ---------------------------------------------------------------------------


class TraceShoreline:
    def __init__(self):
        self.label = "3. Trace Shoreline"
        self.description = (
            "Uses the trained model to draw the low tide, high tide and vegetation "
            "lines on a drone image.")

    def getParameterInfo(self):
        image = _param("Drone image", "image", "GPRasterLayer")
        model = _param("Model (.dlpk)", "model", "DEFile")
        model.filter.list = ["dlpk", "emd"]
        out_folder = _param("Output folder", "out_folder", "DEFolder", direction="Output")
        survey_date = _param("Survey date", "survey_date", "GPString", required=False)
        gpu = _param("Use graphics card", "use_gpu", "GPBoolean", default=True)
        add = _param("Add results to the map", "add_to_map", "GPBoolean", default=True)
        cell = _param("Cell size (m)", "cell_size", "GPDouble", required=False,
                      category="Advanced")
        min_area = _param("Smallest island to keep (m²)", "min_area", "GPDouble",
                          default=50.0, category="Advanced")
        max_hole = _param("Largest hole to fill (m²)", "max_hole", "GPDouble",
                          default=200.0, category="Advanced")
        smooth = _param("Smoothing (m)", "smooth", "GPDouble", default=2.0,
                        category="Advanced")
        gap = _param("High tide gap where vegetation meets the water (m)", "gap",
                     "GPDouble", default=1.0, category="Advanced")
        min_line = _param("Shortest high tide piece to keep (m)", "min_line", "GPDouble",
                          default=5.0, category="Advanced")
        return [image, model, out_folder, survey_date, gpu, add, cell, min_area, max_hole,
                smooth, gap, min_line]

    def isLicensed(self):
        return True

    def execute(self, parameters, messages):
        _needs_image_analyst()
        image = _value_path(parameters[0].value)
        model = parameters[1].valueAsText
        out_folder = parameters[2].valueAsText
        os.makedirs(out_folder, exist_ok=True)

        cell = parameters[6].value
        if cell is None:
            cell = names.read_settings(os.path.dirname(model)).get(
                "cell_size", names.DEFAULT_CELL_SIZE)
        cell = float(cell)

        classified = os.path.join(out_folder, "zones.tif")
        gis.classify(image, model, cell, bool(parameters[4].value), classified, messages)
        outputs = gis.lines_from_zones(
            classified, out_folder,
            min_area=float(parameters[7].value), max_hole=float(parameters[8].value),
            smooth=float(parameters[9].value), gap=float(parameters[10].value),
            min_line=float(parameters[11].value), survey_date=parameters[3].valueAsText,
            messages=messages)
        if parameters[5].value:
            gis.add_to_map(list(outputs.values()), messages)
        messages.addMessage(
            "Check the lines against the image and fix any stretch the model got wrong. "
            "zones.tif in the output folder shows what the model saw: 1 water, "
            "2 intertidal, 3 dry beach, 4 vegetation.")


# ---------------------------------------------------------------------------
# 4. Check Accuracy
# ---------------------------------------------------------------------------


class CheckAccuracy:
    def __init__(self):
        self.label = "4. Check Accuracy"
        self.description = (
            "Measures how far the traced lines are from hand-drawn ones for the same "
            "image.")

    def getParameterInfo(self):
        traced = _param("Traced lines folder", "traced_folder", "DEFolder")
        reference = _param("Hand-drawn lines folder", "reference_folder", "DEFolder")
        out_csv = _param("Output CSV", "out_csv", "DEFile", required=False,
                         direction="Output")
        out_csv.filter.list = ["csv"]
        return [traced, reference, out_csv]

    def isLicensed(self):
        return True

    def execute(self, parameters, messages):
        traced_folder = parameters[0].valueAsText
        reference_folder = parameters[1].valueAsText
        results = []
        for name in names.LINE_NAMES:
            traced = names.find_line_file(traced_folder, name)
            reference = names.find_line_file(reference_folder, name)
            if not traced or not reference:
                missing = traced_folder if not traced else reference_folder
                messages.addWarningMessage(f"{name}: no {name}.shp in {missing}, skipped.")
                continue
            summary = gis.compare(traced, reference, name, messages)
            results.append((name, summary))

        out_csv = parameters[2].valueAsText
        if out_csv and results:
            keys = sorted({key for _, summary in results for key in summary})
            with open(out_csv, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["line"] + keys)
                for name, summary in results:
                    writer.writerow([name] + [summary.get(key, "") for key in keys])
            messages.addMessage(f"Saved the scores to {out_csv}.")
