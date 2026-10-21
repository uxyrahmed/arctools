# -*- coding: utf-8 -*-
"""The arcpy side of the Shoreline Tracing toolbox.

Each public function is one step a tool runs. The zone logic itself lives in
labels.py and the scoring in accuracy.py, which don't need arcpy.
"""

import math
import os

import arcpy

from . import accuracy, labels, names

# How far out to sea and inland the training band reaches, in metres.
SEA_BAND = 60.0
LAND_BAND = 80.0


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _memory(name):
    """A path in the memory workspace, cleared first."""
    path = f"memory\\{name}"
    if arcpy.Exists(path):
        arcpy.management.Delete(path)
    return path


def _scratch_raster(name):
    path = os.path.join(arcpy.env.scratchGDB, name)
    if arcpy.Exists(path):
        arcpy.management.Delete(path)
    return path


def _delete(*paths):
    for path in paths:
        try:
            if path and arcpy.Exists(path):
                arcpy.management.Delete(path)
        except Exception:  # noqa: BLE001 - cleaning up must never stop a tool
            pass


def rgb_raster(image):
    """image as a raster with only its first three bands (red, green, blue).
    Drone orthomosaics often carry a fourth, transparency band, which the model
    must not see."""
    raster = arcpy.Raster(image)
    if raster.bandCount > 3:
        return arcpy.ia.ExtractBand(raster, band_ids=[1, 2, 3])
    return raster


def _burn_field(features, name):
    """Copy features into memory with a field 'burn' set to 1, ready to draw
    onto a grid."""
    copy = _memory(name)
    arcpy.management.CopyFeatures(features, copy)
    arcpy.management.AddField(copy, "burn", "SHORT")
    arcpy.management.CalculateField(copy, "burn", "1", "PYTHON3")
    return copy


def _grid(features, kind, name, origin, size, cell):
    """features drawn onto a True/False grid of size (rows, cols) whose lower
    left corner is origin. kind is 'polygon' or 'line'."""
    burn = _burn_field(features, name + "_burn")
    out = _scratch_raster(name)
    if kind == "polygon":
        arcpy.conversion.PolygonToRaster(burn, "burn", out, "CELL_CENTER", "", cell)
    else:
        arcpy.conversion.PolylineToRaster(burn, "burn", out, "MAXIMUM_LENGTH", "", cell)
    rows, cols = size
    array = arcpy.RasterToNumPyArray(
        out, lower_left_corner=arcpy.Point(*origin), ncols=cols, nrows=rows, nodata_to_value=0)
    _delete(burn, out)
    return array > 0


def _shape_type(features):
    return arcpy.Describe(features).shapeType.lower()


# ---------------------------------------------------------------------------
# Prepare Training Data
# ---------------------------------------------------------------------------


def label_survey(image, low_tide, high_tide, vegetation, cell, reach, messages):
    """Draw one survey's three lines onto a grid and turn them into zones.

    Returns (zones, origin, spatial_reference). zones is the numpy grid from
    labels.make_labels, origin its lower left corner in the image's
    coordinate system.
    """
    for path, label, wanted in (
        (low_tide, "Low tide line", "polygon"),
        (vegetation, "Vegetation line", "polygon"),
        (high_tide, "High tide line", "polyline"),
    ):
        if _shape_type(path) != wanted:
            raise ValueError(
                f"{label} should be {'polygons' if wanted == 'polygon' else 'lines'}, "
                f"but {path} holds {_shape_type(path)} features.")

    sr = arcpy.Describe(image).spatialReference
    image_extent = arcpy.Describe(image).extent
    coast = arcpy.Describe(low_tide).extent.projectAs(sr)
    margin = SEA_BAND + 2 * cell
    xmin = max(coast.XMin - margin, image_extent.XMin)
    ymin = max(coast.YMin - margin, image_extent.YMin)
    xmax = min(coast.XMax + margin, image_extent.XMax)
    ymax = min(coast.YMax + margin, image_extent.YMax)
    if xmin >= xmax or ymin >= ymax:
        raise ValueError(
            f"The low tide line doesn't overlap the drone image {image}. Check the "
            "lines belong to this image.")

    # Line the grid up on whole cells so every layer lands on the same cells.
    xmin = math.floor(xmin / cell) * cell
    ymin = math.floor(ymin / cell) * cell
    cols = int(math.ceil((xmax - xmin) / cell))
    rows = int(math.ceil((ymax - ymin) / cell))

    with arcpy.EnvManager(outputCoordinateSystem=sr, snapRaster=None, cellSize=cell,
                          extent=arcpy.Extent(xmin, ymin, xmin + cols * cell,
                                              ymin + rows * cell)):
        origin = (xmin, ymin)
        low = _grid(low_tide, "polygon", "st_low", origin, (rows, cols), cell)
        veg = _grid(vegetation, "polygon", "st_veg", origin, (rows, cols), cell)
        high = _grid(high_tide, "line", "st_high", origin, (rows, cols), cell)

    messages.addMessage(f"  Drew the lines onto a {cols} x {rows} grid of {cell:g} m cells.")
    zones = labels.make_labels(low, veg, high, cell, high_tide_reach=reach,
                               sea_band=SEA_BAND, land_band=LAND_BAND)
    return zones, origin, sr


def zones_to_polygons(zones, origin, cell, sr, out_fc):
    """Save the zone grid as polygons with Classvalue and Classname fields,
    the form Export Training Data For Deep Learning reads."""
    raster_path = _scratch_raster("st_zones")
    raster = arcpy.NumPyArrayToRaster(zones, arcpy.Point(*origin), cell, cell,
                                      value_to_nodata=labels.NO_LABEL)
    raster.save(raster_path)
    arcpy.management.DefineProjection(raster_path, sr)
    arcpy.conversion.RasterToPolygon(raster_path, out_fc, "NO_SIMPLIFY", "Value")
    arcpy.management.AddField(out_fc, "Classvalue", "LONG")
    arcpy.management.AddField(out_fc, "Classname", "TEXT", field_length=20)
    with arcpy.da.UpdateCursor(out_fc, ["gridcode", "Classvalue", "Classname"]) as cursor:
        for code, _, _ in cursor:
            cursor.updateRow([code, code, labels.CLASS_NAMES.get(code, "")])
    _delete(raster_path)
    return out_fc


def export_tiles(image, zones_fc, mask_fc, out_folder, cell, tile_size):
    """Cut the image and its zones into matching training tiles."""
    stride = tile_size // 2
    with arcpy.EnvManager(cellSize=cell):
        arcpy.ia.ExportTrainingDataForDeepLearning(
            in_raster=rgb_raster(image),
            out_folder=out_folder,
            in_class_data=zones_fc,
            image_chip_format="TIFF",
            tile_size_x=tile_size,
            tile_size_y=tile_size,
            stride_x=stride,
            stride_y=stride,
            output_nofeature_tiles="ONLY_TILES_WITH_FEATURES",
            metadata_format="Classified_Tiles",
            start_index=0,
            class_value_field="Classvalue",
            buffer_radius=0,
            in_mask_polygons=mask_fc,
        )


def prepare_survey(image, low_tide, high_tide, vegetation, out_folder, zones_gdb,
                   name, cell, tile_size, reach, messages):
    """All of Prepare Training Data for one survey."""
    messages.addMessage(f"{name}:")
    zones, origin, sr = label_survey(image, low_tide, high_tide, vegetation, cell,
                                     reach, messages)
    counts = labels.class_counts(zones)
    messages.addMessage("  Zones (cells): " + ", ".join(f"{k} {v:,}" for k, v in counts.items()))
    for zone in ("Intertidal", "Dry beach"):
        if counts[zone] == 0:
            messages.addWarningMessage(
                f"  No {zone.lower()} cells. Check the high tide line lies between the "
                "low tide and vegetation lines.")

    zones_fc = os.path.join(zones_gdb, f"{name}_zones")
    mask_fc = os.path.join(zones_gdb, f"{name}_area")
    _delete(zones_fc, mask_fc)
    zones_to_polygons(zones, origin, cell, sr, zones_fc)
    arcpy.management.Dissolve(zones_fc, mask_fc)
    messages.addMessage(f"  Saved the zones to {zones_fc} so you can check them on the map.")

    survey_folder = os.path.join(out_folder, name)
    export_tiles(image, zones_fc, mask_fc, survey_folder, cell, tile_size)
    tiles = len(os.listdir(os.path.join(survey_folder, "images"))) \
        if os.path.isdir(os.path.join(survey_folder, "images")) else 0
    messages.addMessage(f"  Exported {tiles} training tiles to {survey_folder}.")
    return survey_folder


# ---------------------------------------------------------------------------
# Train Shoreline Model
# ---------------------------------------------------------------------------


def train(folders, model_folder, epochs, batch_size, backbone, arguments, messages):
    messages.addMessage(f"Training on {len(folders)} folder(s) of tiles:")
    for folder in folders:
        messages.addMessage(f"  {folder}")
    arcpy.ia.TrainDeepLearningModel(
        in_folder=folders if len(folders) > 1 else folders[0],
        out_folder=model_folder,
        max_epochs=epochs,
        model_type="UNET",
        batch_size=batch_size,
        arguments=arguments or None,
        backbone_model=backbone,
        validation_percentage=10,
        stop_training="STOP_TRAINING",
        freeze="FREEZE_MODEL",
    )


def find_model_file(model_folder):
    """The .dlpk (or else .emd) that Train Deep Learning Model wrote."""
    for ext in (".dlpk", ".emd"):
        for entry in sorted(os.listdir(model_folder)):
            if entry.lower().endswith(ext):
                return os.path.join(model_folder, entry)
    return None


# ---------------------------------------------------------------------------
# Trace Shoreline
# ---------------------------------------------------------------------------


def classify(image, model, cell, use_gpu, out_raster, messages):
    """Run the model over the image. Returns the zone raster's path."""
    env = {"cellSize": cell}
    if use_gpu:
        env.update(processorType="GPU", gpuId="0")
    else:
        env.update(processorType="CPU")
    messages.addMessage(
        f"Running the model on the {'graphics card' if use_gpu else 'processor'} "
        f"at {cell:g} m. This is the slow step.")
    with arcpy.EnvManager(**env):
        result = arcpy.ia.ClassifyPixelsUsingDeepLearning(
            in_raster=rgb_raster(image),
            in_model_definition=model,
            arguments="padding 64;batch_size 4",
            processing_mode="PROCESS_AS_MOSAICKED_IMAGE",
        )
        result.save(out_raster)
    return out_raster


def _zone_polygon(classified, test, name, min_area, max_hole, smooth):
    """Polygons of the cells where test(classified) holds, with specks
    removed, small holes filled and edges smoothed."""
    raster = arcpy.ia.Con(test(arcpy.Raster(classified)), 1)
    raw = _memory(name + "_raw")
    arcpy.conversion.RasterToPolygon(raster, raw, "SIMPLIFY", "Value")
    dissolved = _memory(name + "_diss")
    arcpy.management.Dissolve(raw, dissolved)
    single = _memory(name + "_single")
    arcpy.management.MultipartToSinglepart(dissolved, single)
    with arcpy.da.UpdateCursor(single, ["SHAPE@AREA"]) as cursor:
        for (area,) in cursor:
            if area < min_area:
                cursor.deleteRow()
    filled = _memory(name + "_filled")
    arcpy.management.EliminatePolygonPart(
        single, filled, "AREA", f"{max_hole} SquareMeters", part_option="CONTAINED_ONLY")
    smoothed = _memory(name + "_smooth")
    arcpy.cartography.SmoothPolygon(filled, smoothed, "PAEK", f"{smooth} Meters")
    _delete(raw, dissolved, single, filled)
    return smoothed


def _erase(in_features, erase_features, out):
    try:
        arcpy.analysis.PairwiseErase(in_features, erase_features, out)
    except Exception:  # noqa: BLE001 - older Pro or licence: fall back
        arcpy.analysis.Erase(in_features, erase_features, out)


def lines_from_zones(classified, out_folder, min_area, max_hole, smooth, gap, min_line,
                     survey_date, messages):
    """Turn the zone raster into the three shapefiles the team draws by hand.

    Low tide line:   polygon around everything that isn't water.
    Vegetation line: polygon around the vegetation zone.
    High tide line:  the seaward edge of the dry beach and vegetation, as
                     lines, with gaps where there's no dry beach (seawalls,
                     buildings at the water), like the hand-drawn ones.
    """
    low = _zone_polygon(classified, lambda r: r >= labels.INTERTIDAL, "st_low",
                        min_area, max_hole, smooth)
    upper = _zone_polygon(classified, lambda r: r >= labels.DRY_BEACH, "st_upper",
                          min_area, max_hole, smooth)
    veg = _zone_polygon(classified, lambda r: r == labels.VEGETATION, "st_veg",
                        min_area, max_hole, smooth)

    upper_line = _memory("st_upper_line")
    arcpy.management.PolygonToLine(upper, upper_line, "IGNORE_NEIGHBORS")
    veg_line = _memory("st_veg_line")
    arcpy.management.PolygonToLine(veg, veg_line, "IGNORE_NEIGHBORS")
    veg_buffer = _memory("st_veg_buffer")
    arcpy.analysis.Buffer(veg_line, veg_buffer, f"{gap} Meters")
    high_raw = _memory("st_high_raw")
    _erase(upper_line, veg_buffer, high_raw)
    high = _memory("st_high")
    arcpy.management.MultipartToSinglepart(high_raw, high)
    with arcpy.da.UpdateCursor(high, ["SHAPE@LENGTH"]) as cursor:
        for (length,) in cursor:
            if length < min_line:
                cursor.deleteRow()

    outputs = {}
    for name, features in ((names.LOW_TIDE, low), (names.HIGH_TIDE, high),
                           (names.VEGETATION, veg)):
        out = os.path.join(out_folder, name + ".shp")
        _delete(out)
        arcpy.management.CopyFeatures(features, out)
        if survey_date:
            arcpy.management.AddField(out, "SurveyDate", "TEXT", field_length=20)
            arcpy.management.CalculateField(out, "SurveyDate", repr(survey_date), "PYTHON3")
        count = int(arcpy.management.GetCount(out)[0])
        messages.addMessage(f"Saved {name}: {count} feature(s), {out}")
        outputs[name] = out
    _delete(low, upper, veg, upper_line, veg_line, veg_buffer, high_raw, high)
    return outputs


def add_to_map(paths, messages):
    """Add the outputs to the active map, when there is one."""
    try:
        project = arcpy.mp.ArcGISProject("CURRENT")
        active = project.activeMap
    except Exception:  # noqa: BLE001 - not running inside Pro
        return
    if active is None:
        return
    for path in paths:
        try:
            active.addDataFromPath(path)
        except Exception as error:  # noqa: BLE001
            messages.addWarningMessage(f"Couldn't add {path} to the map: {error}")


# ---------------------------------------------------------------------------
# Check Accuracy
# ---------------------------------------------------------------------------


def _as_lines(features, name):
    if _shape_type(features) == "polygon":
        out = _memory(name)
        arcpy.management.PolygonToLine(features, out, "IGNORE_NEIGHBORS")
        return out
    return features


def compare(traced, reference, name, messages, spacing=1.0):
    """How far the hand-drawn line (reference) is from the traced one, from a
    point every spacing metres along the hand-drawn line."""
    ref_lines = _as_lines(reference, "st_ref_lines")
    traced_lines = _as_lines(traced, "st_traced_lines")
    points = _memory("st_ref_points")
    sr = arcpy.Describe(reference).spatialReference
    with arcpy.EnvManager(outputCoordinateSystem=sr):
        arcpy.management.GeneratePointsAlongLines(
            ref_lines, points, "DISTANCE", Distance=f"{spacing} Meters")
        arcpy.analysis.Near(points, traced_lines)
    distances = []
    with arcpy.da.SearchCursor(points, ["NEAR_DIST"]) as cursor:
        for (distance,) in cursor:
            distances.append(distance if distance is not None and distance >= 0 else None)
    _delete(points)
    if ref_lines != reference:
        _delete(ref_lines)
    if traced_lines != traced:
        _delete(traced_lines)
    summary = accuracy.summarise(distances)
    messages.addMessage(accuracy.report_line(name, summary))
    return summary
