# -*- coding: utf-8 -*-
"""Step 3: draw an arrow for each current, from where it started to where it
ended, labelled with its speed and direction. The points and times come from
the currents CSV; see currents.py."""

import os

import arcpy

from . import currents, gis, messages, surveys


def arrows_path(gdb):
    return os.path.join(str(gdb), surveys.by_code(surveys.CURRENT_ARROWS).feature_class)


def draw_current_arrows(csv_path, gdb, coordinate_system=None):
    """Work out each current's speed and direction from the CSV and write an
    arrow for each, start to end, to C_Arrows in gdb. A current that can't be
    worked out is skipped with a warning.

    Distances are worked out in coordinate_system if it is projected,
    otherwise in WGS 1984 UTM Zone 43N (or 43S south of the equator). The
    arrows are saved in WGS 1984, like the survey data. Returns the number of
    arrows drawn.
    """
    gdb = str(gdb or "")
    if not gdb.lower().endswith(".gdb") or not arcpy.Exists(gdb):
        raise surveys.SurveyMapError(
            f"Choose the file geodatabase that Step 1 made (a .gdb folder), not: {gdb}"
        )
    readings, problems = currents.read_csv(csv_path)
    arcpy.AddMessage(f"Read {surveys.plural(len(readings), 'point')} from the currents CSV.")
    readings, others = currents.only_currents(readings)
    if others:
        arcpy.AddMessage(f"Left out {surveys.plural(others, 'point')} that aren't current points.")
    found, more = currents.pair_readings(readings)
    for problem in problems + more:
        arcpy.AddWarning(problem)
    if not found:
        raise surveys.SurveyMapError(
            "No current in the CSV has both a start and an end point with a time, "
            "so no arrows were drawn. Name each current's points like 'C1 start' "
            "and 'C1 end'."
        )

    wgs84 = arcpy.SpatialReference(gis.WGS84)
    try:
        geometries = {
            id(reading): arcpy.PointGeometry(
                arcpy.Point(reading.x, reading.y), arcpy.SpatialReference(reading.wkid)
            )
            for current in found
            for reading in (current.start, current.end)
        }
    except Exception as error:
        raise surveys.SurveyMapError(
            messages.problem(error, "make points from the currents CSV")
        ) from error

    if coordinate_system is not None and coordinate_system.type == "Projected":
        work_sr = coordinate_system
    else:
        if coordinate_system is not None:
            arcpy.AddWarning(
                f"{gis.describe_spatial_reference(coordinate_system)} isn't a "
                "projected coordinate system, so distances are worked out in UTM "
                "instead."
            )
        work_sr = gis.default_utm(list(geometries.values()))
    metres = work_sr.metersPerUnit

    features = []
    for current in found:
        with gis.carry_on(f"draw the arrow for {current.name}", so="it has no arrow"):
            start = gis.project(geometries[id(current.start)], work_sr).firstPoint
            end = gis.project(geometries[id(current.end)], work_sr).firstPoint
            values = currents.measure(
                current, (end.X - start.X) * metres, (end.Y - start.Y) * metres
            )
            line = arcpy.Polyline(
                arcpy.Array([arcpy.Point(start.X, start.Y), arcpy.Point(end.X, end.Y)]),
                work_sr,
            )
            features.append((current.name, gis.project(line, wgs84)) + tuple(values.values()))
            arcpy.AddMessage("  " + currents.describe(current.name, values))

    # Written even when empty, so no arrows from an earlier run are left.
    gis.write_features(
        arrows_path(gdb), surveys.POLYLINE, wgs84, features,
        extra_fields=currents.ARROW_FIELDS,
    )
    if not features:
        raise surveys.SurveyMapError(
            "None of the currents could be drawn. The warnings above say why."
        )
    arcpy.AddMessage(
        f"Drew {surveys.plural(len(features), 'current arrow')}, worked out in "
        f"{gis.describe_spatial_reference(work_sr)}."
    )
    return len(features)
