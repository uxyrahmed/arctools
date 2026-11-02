# -*- coding: utf-8 -*-
"""Step 1: draw an arrow for each current, from where it started to where it
ended, labelled with its speed and direction. The points and times come from
the currents CSV; see currents.py."""

import os

import arcpy

from . import common, currents, gis, messages


def arrows_path(gdb):
    return os.path.join(str(gdb), common.ARROWS_FEATURE_CLASS)


def points_path(gdb):
    return os.path.join(str(gdb), common.POINTS_FEATURE_CLASS)


def make_geodatabase(folder, name):
    """The path of the file geodatabase name.gdb in folder, made if it isn't
    there yet. An existing one, such as a survey geodatabase, is used as it is."""
    folder = str(folder or "")
    name = str(name or "").strip()
    if name.lower().endswith(".gdb"):
        name = name[:-4]
    if not folder or not os.path.isdir(folder):
        raise common.CurrentsMapError(f"The output folder isn't there: {folder}")
    if not name:
        raise common.CurrentsMapError("Give the geodatabase a name.")
    gdb = os.path.join(folder, name + ".gdb")
    if arcpy.Exists(gdb):
        arcpy.AddMessage(f"Writing to the geodatabase that's already there: {gdb}")
        return gdb
    try:
        gis.retry_on_lock(arcpy.management.CreateFileGDB, folder, name)
    except Exception as error:
        raise common.CurrentsMapError(
            messages.problem(error, f"make the geodatabase {name}.gdb")
        ) from error
    arcpy.AddMessage(f"Made the geodatabase {gdb}")
    return gdb


def check_geodatabase(gdb):
    path = str(gdb or "")
    if not path.lower().endswith(".gdb") or not arcpy.Exists(path):
        raise common.CurrentsMapError(
            f"Choose a file geodatabase (a .gdb folder), not: {path}"
        )
    return path


def draw_current_arrows(csv_path, gdb, coordinate_system=None):
    """Work out each current's speed and direction from the CSV and write an
    arrow for each, start to end, to C_Arrows in gdb, and its start and end
    points to C_Points. A current that can't be worked out is skipped with a
    warning.

    Distances, and X and Y of the points, are in coordinate_system if it is
    projected, otherwise in WGS 1984 UTM Zone 43N (or 43S south of the
    equator). The data is saved in WGS 1984. Returns the number of arrows.
    """
    gdb = check_geodatabase(gdb)
    readings, problems = currents.read_csv(csv_path)
    arcpy.AddMessage(f"Read {common.plural(len(readings), 'point')} from the currents CSV.")
    readings, others = currents.only_currents(readings)
    if others:
        arcpy.AddMessage(f"Left out {common.plural(others, 'point')} that aren't current points.")
    found, more = currents.pair_readings(readings)
    for problem in problems + more:
        arcpy.AddWarning(problem)
    if not found:
        raise common.CurrentsMapError(
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
        raise common.CurrentsMapError(
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

    arrows, points = [], []
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
            arrows.append((current.name, gis.project(line, wgs84)) + tuple(values.values()))
            for (name, fields), reading in zip(
                currents.point_values(current), (current.start, current.end)
            ):
                points.append((name, gis.project(geometries[id(reading)], wgs84)) + fields)
            arcpy.AddMessage("  " + currents.describe(current.name, values))

    # Written even when empty, so nothing from an earlier run is left.
    gis.write_features(
        arrows_path(gdb), "POLYLINE", wgs84, arrows, extra_fields=currents.ARROW_FIELDS,
    )
    with gis.carry_on(f"write the start and end points to {common.POINTS_FEATURE_CLASS}",
                      so="only the arrows are saved"):
        gis.write_features(
            points_path(gdb), "POINT", wgs84, points, xy_sr=work_sr,
            extra_fields=currents.POINT_FIELDS,
        )
    if not arrows:
        raise common.CurrentsMapError(
            "None of the currents could be drawn. The warnings above say why."
        )
    arcpy.AddMessage(
        f"Drew {common.plural(len(arrows), 'current arrow')} in {gdb}, worked out in "
        f"{gis.describe_spatial_reference(work_sr)}."
    )
    return len(arrows)
