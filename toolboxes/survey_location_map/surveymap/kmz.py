# -*- coding: utf-8 -*-
"""Step 1: turn a survey KMZ into one clean feature class per survey."""

import os
import uuid
from collections import Counter, defaultdict

import arcpy

from . import gis, surveys

_GEOMETRIES = {"Point": surveys.POINT, "Polyline": surveys.POLYLINE}


def geodatabase_path(folder, name):
    name = str(name).strip()
    if name.lower().endswith(".gdb"):
        name = name[:-4]
    return os.path.join(str(folder), name + ".gdb")


def ensure_geodatabase(folder, name):
    """The file geodatabase folder/name.gdb, created if it doesn't exist yet."""
    if not os.path.isdir(str(folder)):
        raise surveys.SurveyMapError(f"The output folder doesn't exist: {folder}")
    path = geodatabase_path(folder, name)
    if not arcpy.Exists(path):
        arcpy.management.CreateFileGDB(str(folder), os.path.basename(path)[:-4])
        arcpy.AddMessage(f"Created {path}")
    return path


def import_kmz(kmz_path, out_folder, gdb_name, coordinate_system=None):
    """Convert the KMZ, split its features by survey and write Name (and X, Y
    for points) to one feature class per survey.

    Returns (geodatabase path, list of feature classes written).
    """
    gdb = ensure_geodatabase(out_folder, gdb_name)
    found = _read_kmz(kmz_path)
    groups, unknown, unnamed, skipped, source_sr = found

    if not groups and not unknown:
        raise surveys.SurveyMapError(
            "No survey points or lines were found in the KMZ. Point names need "
            "to start with a survey prefix such as SW, VSS, T, P, BP, GW, C or N."
        )

    if coordinate_system is None:
        point_geometries = [
            geometry
            for code, features in groups.items()
            if surveys.by_code(code).is_point
            for _, geometry in features
        ]
        point_geometries += [g for features in unknown.values() for _, g in features]
        xy_sr = gis.default_utm(point_geometries)
    else:
        xy_sr = coordinate_system

    written = []
    for survey in surveys.SURVEYS:
        path = os.path.join(gdb, survey.feature_class)
        features = groups.get(survey.code)
        if features:
            gis.write_features(
                path, survey.geometry, source_sr, features,
                xy_sr if survey.is_point else None,
            )
            kind = "point" if survey.is_point else "line"
            arcpy.AddMessage(
                f"  {survey.layer_name}: {surveys.plural(len(features), kind)} -> "
                f"{survey.feature_class}"
            )
            written.append(path)
        elif gis.delete_if_exists(path):
            # Left over from an earlier run, so it doesn't match this KMZ.
            note = " Step 2 draws them again from these points." if not survey.prefixes else ""
            arcpy.AddMessage(f"  Removed {survey.feature_class} from an earlier run.{note}")

    for prefix in sorted(unknown):
        fc_name = surveys.unknown_feature_class(prefix)
        path = os.path.join(gdb, fc_name)
        gis.write_features(path, surveys.POINT, source_sr, unknown[prefix], xy_sr)
        written.append(path)
        arcpy.AddWarning(
            f"Found {surveys.plural(len(unknown[prefix]), 'point')} starting with "
            f"'{prefix}', which isn't a known survey prefix. They are saved in "
            f"{fc_name} but won't go on the map. To map them, add the survey to "
            "SURVEYS in surveymap/surveys.py and to the master layout."
        )

    if unnamed:
        arcpy.AddWarning(
            f"Left out {surveys.plural(len(unnamed), 'point')} with no letters at "
            f"the start of the name: {_examples(unnamed)}"
        )
    if skipped:
        counts = ", ".join(surveys.plural(n, kind) for kind, n in sorted(skipped.items()))
        arcpy.AddMessage(f"Left out features that aren't survey data: {counts}.")
    arcpy.AddMessage(f"X and Y are in {gis.describe_spatial_reference(xy_sr)}.")
    return gdb, written


def _read_kmz(kmz_path):
    """Convert the KMZ in the scratch folder and sort its features by survey.

    Returns (groups, unknown, unnamed, skipped, spatial reference):
    groups maps survey code -> [(name, geometry)], unknown maps an unknown
    point prefix -> [(name, geometry)], unnamed lists point names with no
    letter prefix, and skipped counts the features left out by kind.
    """
    scratch = arcpy.env.scratchFolder
    name = "kmz_" + uuid.uuid4().hex[:12]
    arcpy.conversion.KMLToLayer(str(kmz_path), scratch, name, "NO_GROUNDOVERLAY")
    raw_gdb = os.path.join(scratch, name + ".gdb")

    groups = defaultdict(list)
    unknown = defaultdict(list)
    unnamed = []
    skipped = Counter()
    source_sr = None
    try:
        for dirpath, _dirnames, filenames in arcpy.da.Walk(raw_gdb, datatype="FeatureClass"):
            for filename in filenames:
                path = os.path.join(dirpath, filename)
                description = arcpy.Describe(path)
                geometry_type = _GEOMETRIES.get(description.shapeType)
                name_field = _name_field(path)
                with arcpy.da.SearchCursor(path, [name_field, "SHAPE@"]) as rows:
                    for feature_name, geometry in rows:
                        if geometry is None:
                            continue
                        feature_name = (feature_name or "").strip()
                        if geometry_type is None:
                            skipped[_noun(description.shapeType)] += 1
                            continue
                        survey = surveys.survey_for(feature_name, geometry_type)
                        if survey is not None:
                            groups[survey.code].append((feature_name, geometry))
                        elif geometry_type == surveys.POINT:
                            prefix = surveys.name_prefix(feature_name)
                            if prefix:
                                unknown[prefix].append((feature_name, geometry))
                            else:
                                unnamed.append(feature_name or "(no name)")
                        else:
                            skipped["line"] += 1
                            continue
                        if source_sr is None:
                            source_sr = description.spatialReference
    finally:
        gis.delete_if_exists(raw_gdb)
        layer_file = os.path.join(scratch, name + ".lyrx")
        if os.path.exists(layer_file):
            os.remove(layer_file)

    for features in list(groups.values()) + list(unknown.values()):
        features.sort(key=lambda feature: surveys.natural_key(feature[0]))
    total = sum(len(f) for f in groups.values()) + sum(len(f) for f in unknown.values())
    total += len(unnamed) + sum(skipped.values())
    arcpy.AddMessage(f"Read {surveys.plural(total, 'feature')} from the KMZ.")
    return groups, unknown, unnamed, skipped, source_sr


def _name_field(path):
    for field in arcpy.ListFields(path):
        if field.name.lower() == "name":
            return field.name
    raise surveys.SurveyMapError(f"The KMZ layer {os.path.basename(path)} has no Name field.")


def _noun(shape_type):
    return {"Polygon": "polygon", "MultiPatch": "3D model", "Multipoint": "multipoint"}.get(
        shape_type, str(shape_type).lower()
    )


def _examples(names, limit=5):
    shown = ", ".join(names[:limit])
    return shown + (f" and {len(names) - limit} more" if len(names) > limit else "")
