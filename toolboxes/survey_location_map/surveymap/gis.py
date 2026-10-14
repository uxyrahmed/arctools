# -*- coding: utf-8 -*-
"""Small arcpy helpers shared by the tools."""

import os

import arcpy

from . import surveys

WGS84 = 4326


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
    """WGS 1984 UTM Zone 43N, or 43S if the data is south of the equator."""
    return arcpy.SpatialReference(surveys.utm_wkid(mean_latitude(geometries)))


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


def count(dataset):
    return int(arcpy.management.GetCount(dataset)[0])


def delete_if_exists(dataset):
    if arcpy.Exists(dataset):
        arcpy.management.Delete(dataset)
        return True
    return False


def write_features(path, geometry_type, spatial_reference, features, xy_sr=None):
    """Write features to a new feature class with a Name field, plus X and Y
    in xy_sr when xy_sr is given."""
    delete_if_exists(path)
    folder, name = os.path.split(path)
    arcpy.management.CreateFeatureclass(
        folder, name, geometry_type, spatial_reference=spatial_reference
    )
    arcpy.management.AddField(path, "Name", "TEXT", field_length=255)
    if xy_sr is not None:
        arcpy.management.AddField(path, "X", "DOUBLE")
        arcpy.management.AddField(path, "Y", "DOUBLE")

    with arcpy.da.InsertCursor(path, ["Name", "SHAPE@"]) as rows:
        for feature_name, geometry in features:
            rows.insertRow([feature_name, geometry])

    if xy_sr is not None:
        arcpy.management.CalculateGeometryAttributes(
            path, [["X", "POINT_X"], ["Y", "POINT_Y"]], coordinate_system=xy_sr
        )
        decimals = (
            surveys.XY_DECIMALS_DEGREES if xy_sr.type == "Geographic" else surveys.XY_DECIMALS
        )
        with arcpy.da.UpdateCursor(path, ["X", "Y"]) as rows:
            for x, y in rows:
                if x is not None and y is not None:
                    rows.updateRow([round(x, decimals), round(y, decimals)])
