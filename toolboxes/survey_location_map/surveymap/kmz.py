# -*- coding: utf-8 -*-
"""Step 1: turn a survey KMZ into one clean feature class per survey."""

import os
import tempfile
from collections import Counter, defaultdict

import arcpy

from . import gis, messages, surveys

_GEOMETRIES = {"Point": surveys.POINT, "Polyline": surveys.POLYLINE}

# Feature classes the other steps make, and which step makes them again.
_REDRAWN_BY = {
    surveys.TRANSECT_LINES: " Step 2 draws them again from the transect points.",
    surveys.CURRENT_ARROWS: " Step 3 draws them again from the currents CSV.",
}


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
        try:
            gis.retry_on_lock(
                arcpy.management.CreateFileGDB, str(folder), os.path.basename(path)[:-4]
            )
        except Exception as error:
            raise surveys.SurveyMapError(messages.problem(error, f"create {path}")) from error
        arcpy.AddMessage(f"Created {path}")
    return path


def import_kmz(kmz_path, out_folder, gdb_name, coordinate_system=None):
    """Convert the KMZ, split its features by survey and write Name (and X, Y
    for points) to one feature class per survey.

    A survey that can't be written is skipped with a warning, and the rest
    carry on. Returns (geodatabase path, {survey code: features written}).
    """
    gdb = ensure_geodatabase(out_folder, gdb_name)
    groups, unknown, unnamed, skipped, source_sr = _read_kmz(kmz_path)

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

    written, failed = {}, []
    for survey in surveys.SURVEYS:
        path = os.path.join(gdb, survey.feature_class)
        features = groups.get(survey.code)
        if features:
            with gis.carry_on(f"write {survey.feature_class}") as outcome:
                gis.write_features(
                    path, survey.geometry, source_sr, features,
                    xy_sr if survey.is_point else None,
                )
            if not outcome.ok:
                failed.append(survey.feature_class)
                continue
            kind = "point" if survey.is_point else "line"
            arcpy.AddMessage(
                f"  {survey.layer_name}: {surveys.plural(len(features), kind)} -> "
                f"{survey.feature_class}"
            )
            written[survey.code] = len(features)
        elif arcpy.Exists(path) and gis.clear_features(path):
            # Left from an earlier run, so it doesn't match this KMZ.
            note = _REDRAWN_BY.get(survey.code, "")
            arcpy.AddMessage(f"  Cleared {survey.feature_class}, left from an earlier run.{note}")

    for prefix in sorted(unknown):
        fc_name = surveys.unknown_feature_class(prefix)
        with gis.carry_on(f"write {fc_name}") as outcome:
            gis.write_features(
                os.path.join(gdb, fc_name), surveys.POINT, source_sr, unknown[prefix], xy_sr
            )
        saved = (
            f"They are saved in {fc_name} but won't go on the map."
            if outcome.ok else "They won't go on the map."
        )
        arcpy.AddWarning(
            f"Found {surveys.plural(len(unknown[prefix]), 'point')} starting with "
            f"'{prefix}', which isn't a known survey prefix. {saved} To map them, "
            "add the survey to SURVEYS in surveymap/surveys.py and to the master "
            "layout."
        )

    if failed and not written:
        raise surveys.SurveyMapError(
            f"None of the survey data could be written to {gdb}, so the tool "
            "stopped. The warnings above say why."
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
    """Convert the KMZ in a temporary folder and sort its features by survey.

    Returns (groups, unknown, unnamed, skipped, spatial reference):
    groups maps survey code -> [(name, geometry)], unknown maps an unknown
    point prefix -> [(name, geometry)], unnamed lists point names with no
    letter prefix, and skipped counts the features left out by kind.
    """
    # The converted copy goes in Windows' temporary folder rather than the
    # project's scratch folder, which can be in OneDrive, and it's cleared up
    # without ever stopping the tool.
    folder = tempfile.mkdtemp(prefix="surveymap_")
    try:
        try:
            arcpy.conversion.KMLToLayer(str(kmz_path), folder, "survey_kmz", "NO_GROUNDOVERLAY")
        except Exception as error:
            raise surveys.SurveyMapError(messages.problem(error, "read the KMZ")) from error
        found = _sort_features(os.path.join(folder, "survey_kmz.gdb"))
    finally:
        gis.remove_folder(folder)

    groups, unknown, unnamed, skipped, _ = found
    for features in list(groups.values()) + list(unknown.values()):
        features.sort(key=lambda feature: surveys.natural_key(feature[0]))
    total = sum(len(f) for f in groups.values()) + sum(len(f) for f in unknown.values())
    total += len(unnamed) + sum(skipped.values())
    arcpy.AddMessage(f"Read {surveys.plural(total, 'feature')} from the KMZ.")
    return found


def _sort_features(raw_gdb):
    """Sort the features of every feature class KML To Layer made by survey."""
    groups = defaultdict(list)
    unknown = defaultdict(list)
    unnamed = []
    skipped = Counter()
    source_sr = None
    for dirpath, _dirnames, filenames in arcpy.da.Walk(raw_gdb, datatype="FeatureClass"):
        for filename in filenames:
            read = None
            with gis.carry_on(f"read {filename} from the KMZ", so="its features are left out"):
                read = _read_features(os.path.join(dirpath, filename))
            if read is None:
                continue
            shape_type, spatial_reference, features = read
            geometry_type = _GEOMETRIES.get(shape_type)
            for feature_name, geometry in features:
                if geometry_type is None:
                    skipped[_noun(shape_type)] += 1
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
                    source_sr = spatial_reference
    return groups, unknown, unnamed, skipped, source_sr


def _read_features(path):
    """(shape type, spatial reference, [(name, geometry)]) for one feature class.
    Everything is read before returning, so nothing keeps it open."""
    description = arcpy.Describe(path)
    shape_type, spatial_reference = description.shapeType, description.spatialReference
    name_field = _name_field(path)
    with arcpy.da.SearchCursor(path, [name_field, "SHAPE@"]) as rows:
        features = [
            ((name or "").strip(), geometry) for name, geometry in rows if geometry is not None
        ]
    return shape_type, spatial_reference, features


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
