# -*- coding: utf-8 -*-
"""Small arcpy helpers shared by the tools, including the ones that let a tool
warn about a problem and carry on instead of stopping."""

import os
import shutil
import time
import traceback

import arcpy

from . import messages, surveys

WGS84 = 4326

# Locked data is often free again a moment later, for example once OneDrive
# has synced it, so it's tried this many more times before giving up.
LOCK_RETRIES = 2
LOCK_WAIT_SECONDS = 1.0


# --- Problems ---------------------------------------------------------------


def report(error, what=None, so=None, warning=True):
    """Add a message about error to the tool's messages: a warning when the
    tool carries on, an error when it stops. When the error looks like a bug,
    the Python details follow, for troubleshooting."""
    add = arcpy.AddWarning if warning else arcpy.AddError
    add(messages.problem(error, what, so))
    if messages.needs_details(error):
        details = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        arcpy.AddMessage("Details for troubleshooting (send these if you report it):\n" + details)


class carry_on:
    """Run a block, and if it fails, warn and carry on instead of stopping the
    tool:

        with gis.carry_on("label 'Beach Profiles'") as outcome:
            ...
        if outcome.ok:
            ...

    The warning reads "Couldn't <what>, so <so>. <what went wrong>".
    """

    def __init__(self, what, so=None):
        self.what, self.so = what, so
        self.ok = True

    def __enter__(self):
        return self

    def __exit__(self, kind, error, tb):
        if error is None or not isinstance(error, Exception):
            return False
        self.ok = False
        report(error, self.what, self.so)
        return True


class outputs_off_map:
    """Stop ArcGIS Pro adding the data the tools make along the way to the open
    map, where it would be held open and couldn't be replaced or deleted."""

    def __enter__(self):
        self.before = None
        try:
            self.before = arcpy.env.addOutputsToMap
            arcpy.env.addOutputsToMap = False
        except Exception:
            pass
        return self

    def __exit__(self, *exc):
        if self.before is not None:
            try:
                arcpy.env.addOutputsToMap = self.before
            except Exception:
                pass
        return False


def retry_on_lock(function, *args, **kwargs):
    """Call function, trying again a couple of times if the data is locked."""
    attempt = 0
    while True:
        try:
            return function(*args, **kwargs)
        except Exception as error:
            if attempt >= LOCK_RETRIES or not messages.is_lock_error(error):
                raise
        attempt += 1
        time.sleep(LOCK_WAIT_SECONDS * attempt)


# --- Coordinate systems -----------------------------------------------------


def to_spatial_reference(value):
    """A SpatialReference from a coordinate system parameter value, or None if
    the parameter was left empty."""
    if value is None or value == "":
        return None
    if hasattr(value, "exportToString") and hasattr(value, "factoryCode"):
        return value
    text = str(value)
    spatial_reference = arcpy.SpatialReference()
    try:
        spatial_reference.loadFromString(text)
        return spatial_reference
    except Exception:
        return arcpy.SpatialReference(text)


def mean_latitude(geometries):
    """Average latitude of the first point of each geometry."""
    wgs84 = arcpy.SpatialReference(WGS84)
    latitudes = []
    for geometry in geometries:
        if geometry is None or geometry.firstPoint is None:
            continue
        spatial_reference = geometry.spatialReference
        if spatial_reference is not None and spatial_reference.type == "Projected":
            geometry = geometry.projectAs(wgs84)
        latitudes.append(geometry.firstPoint.Y)
    return sum(latitudes) / len(latitudes) if latitudes else 0.0


def default_utm(geometries):
    """WGS 1984 UTM Zone 43N, or 43S if the data is south of the equator. If
    that can't be worked out, 43N, with a warning."""
    with carry_on("work out whether the data is north or south of the equator",
                  so="WGS 1984 UTM Zone 43N is used"):
        return arcpy.SpatialReference(surveys.utm_wkid(mean_latitude(geometries)))
    return arcpy.SpatialReference(surveys.UTM_NORTH_WKID)


def describe_spatial_reference(spatial_reference):
    name = spatial_reference.name.replace("_", " ")
    code = spatial_reference.factoryCode
    return f"{name} (WKID {code})" if code else name


def same_spatial_reference(a, b):
    if a is None or b is None:
        return False
    if a.factoryCode and b.factoryCode:
        return a.factoryCode == b.factoryCode
    return a.exportToString() == b.exportToString()


def project(geometry, spatial_reference):
    if same_spatial_reference(geometry.spatialReference, spatial_reference):
        return geometry
    return geometry.projectAs(spatial_reference)


# --- Data -------------------------------------------------------------------


def count(dataset):
    return int(arcpy.management.GetCount(dataset)[0])


def write_features(path, geometry_type, spatial_reference, features, xy_sr=None):
    """Write features, a list of (name, geometry), to the feature class at
    path, with a Name field, plus X and Y in xy_sr when xy_sr is given.

    A feature class already at path with the same shape, coordinate system
    and fields is emptied and filled again rather than replaced, so this works
    while a map in ArcGIS Pro shows it. Raises SurveyMapError if the features
    can't be written. If only X and Y can't be worked out, it warns and leaves
    them empty.
    """
    name = os.path.basename(path)
    fields = ["Name"] + (["X", "Y"] if xy_sr is not None else [])
    try:
        if not _can_reuse(path, geometry_type, spatial_reference, fields):
            retry_on_lock(_create, path, geometry_type, spatial_reference, fields)
        retry_on_lock(_fill, path, features)
    except Exception as error:
        raise surveys.SurveyMapError(messages.problem(error, f"write {name}")) from error
    if xy_sr is not None:
        with carry_on(f"work out X and Y for {name}", so="they're left empty"):
            retry_on_lock(_calculate_xy, path, xy_sr)


def clear_features(path):
    """Delete the features in a feature class left from an earlier run,
    keeping the feature class itself. Returns how many were deleted, or None
    after a warning if they couldn't be."""
    with carry_on(f"clear {os.path.basename(path)}, left from an earlier run"):
        return retry_on_lock(_empty, path)
    return None


def remove_folder(folder):
    """Delete a folder of working files. Anything ArcGIS Pro still has open is
    left for Windows to clear up rather than stopping the tool."""
    shutil.rmtree(folder, ignore_errors=True)


def _can_reuse(path, geometry_type, spatial_reference, fields):
    """Whether the feature class at path has this shape, coordinate system and
    fields, and no others."""
    try:
        if not arcpy.Exists(path):
            return False
        description = arcpy.Describe(path)
        if str(description.shapeType).upper() != geometry_type:
            return False
        if not same_spatial_reference(description.spatialReference, spatial_reference):
            return False
        found = {
            field.name.casefold(): field.type
            for field in arcpy.ListFields(path)
            if not field.required
        }
    except Exception:
        return False
    wanted = {field.casefold(): "String" if field == "Name" else "Double" for field in fields}
    return found == wanted


def _create(path, geometry_type, spatial_reference, fields):
    if arcpy.Exists(path):
        arcpy.management.Delete(path)
    folder, name = os.path.split(path)
    arcpy.management.CreateFeatureclass(
        folder, name, geometry_type, spatial_reference=spatial_reference
    )
    for field in fields:
        if field == "Name":
            arcpy.management.AddField(path, field, "TEXT", field_length=255)
        else:
            arcpy.management.AddField(path, field, "DOUBLE")


def _empty(path):
    """Delete every feature, keeping the feature class. Unlike deleting the
    feature class, this works while a map in ArcGIS Pro shows it."""
    deleted = 0
    with arcpy.da.UpdateCursor(path, ["OID@"]) as rows:
        for _ in rows:
            rows.deleteRow()
            deleted += 1
    return deleted


def _fill(path, features):
    _empty(path)
    with arcpy.da.InsertCursor(path, ["Name", "SHAPE@"]) as rows:
        for feature_name, geometry in features:
            rows.insertRow([feature_name, geometry])


def _calculate_xy(path, xy_sr):
    arcpy.management.CalculateGeometryAttributes(
        path, [["X", "POINT_X"], ["Y", "POINT_Y"]], coordinate_system=xy_sr
    )
    decimals = surveys.XY_DECIMALS_DEGREES if xy_sr.type == "Geographic" else surveys.XY_DECIMALS
    with arcpy.da.UpdateCursor(path, ["X", "Y"]) as rows:
        for x, y in rows:
            if x is not None and y is not None:
                rows.updateRow([round(x, decimals), round(y, decimals)])
