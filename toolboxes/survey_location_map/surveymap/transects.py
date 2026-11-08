# -*- coding: utf-8 -*-
"""Step 2: draw a line from each transect point in the direction its name
gives, keeping any transect lines that were already in the KMZ."""

import os

import arcpy

from . import directions, gis, messages, surveys


def draw_transect_lines(in_points, out_lines, length_m=surveys.TRANSECT_LENGTH_M,
                        coordinate_system=None):
    """Write the transect lines to out_lines: the ones that were in the KMZ
    (saved by Step 1 next to the points), and a line length_m long from each
    point in in_points that doesn't have one there, in the compass direction
    in its name ('T201 S 2m' goes south). Points with no direction in their
    name get no line, and a point whose line can't be drawn is skipped with a
    warning.

    Lines are worked out in coordinate_system if it is projected, otherwise in
    WGS 1984 UTM Zone 43N (or 43S south of the equator), and saved in the
    points' own coordinate system. Returns the number of transect lines
    written, kept and drawn.
    """
    if length_m is None or length_m <= 0:
        raise surveys.SurveyMapError("The line length must be more than 0 metres.")

    try:
        source_sr = arcpy.Describe(in_points).spatialReference
        name_field = _name_field(in_points)
        with arcpy.da.SearchCursor(in_points, [name_field, "SHAPE@"]) as rows:
            points = [(name or "", geometry) for name, geometry in rows if geometry is not None]
    except surveys.SurveyMapError:
        raise
    except Exception as error:
        raise surveys.SurveyMapError(messages.problem(error, "read the transect points")) from error

    if coordinate_system is not None and coordinate_system.type == "Projected":
        work_sr = coordinate_system
    else:
        if coordinate_system is not None:
            arcpy.AddWarning(
                f"{gis.describe_spatial_reference(coordinate_system)} isn't a "
                "projected coordinate system, so the lines are worked out in UTM "
                "instead."
            )
        work_sr = gis.default_utm([geometry for _, geometry in points])
    distance = length_m / work_sr.metersPerUnit

    kept = []
    for name, geometry in _lines_from_kmz(in_points):
        with gis.carry_on(f"keep the line for {name} from the KMZ", so="it's left out"):
            kept.append((name, gis.project(geometry, source_sr)))
    have_lines = set()
    if kept:
        with gis.carry_on(
            "match the transect points to the lines from the KMZ",
            so="every transect point gets a drawn line as well",
        ):
            have_lines = surveys.points_with_lines(
                [(name, _xy(gis.project(geometry, work_sr).firstPoint))
                 for name, geometry in points],
                [(name, [_xy(line.firstPoint), _xy(line.lastPoint)])
                 for name, line in ((n, gis.project(g, work_sr)) for n, g in kept)],
                surveys.TRANSECT_MATCH_M / work_sr.metersPerUnit,
            )

    lines = []
    no_direction = []
    for index, (name, geometry) in enumerate(points):
        if index in have_lines:
            continue
        bearing = directions.parse_direction(name)
        if bearing is None:
            no_direction.append(name or "(no name)")
            continue
        with gis.carry_on(f"draw the line for {name}", so="that point has no line"):
            start = gis.project(geometry, work_sr).firstPoint
            end_x, end_y = directions.offset(start.X, start.Y, bearing, distance)
            line = arcpy.Polyline(
                arcpy.Array([arcpy.Point(start.X, start.Y), arcpy.Point(end_x, end_y)]),
                work_sr,
            )
            lines.append((name, gis.project(line, source_sr)))
    features = sorted(kept + lines, key=lambda feature: surveys.natural_key(feature[0]))

    gis.write_features(out_lines, surveys.POLYLINE, source_sr, features)

    if kept:
        arcpy.AddMessage(
            f"Kept {surveys.plural(len(kept), 'transect line')} from the KMZ: "
            + ", ".join(name or "(no name)" for name, _ in kept) + "."
        )
    if lines or not kept:
        others = " for the transect points without one" if kept else ""
        arcpy.AddMessage(
            f"Drew {surveys.plural(len(lines), 'transect line')}{others}, "
            f"{length_m:g} m long, worked out in "
            f"{gis.describe_spatial_reference(work_sr)}."
        )
    elif not no_direction:
        arcpy.AddMessage("Every transect point has a line from the KMZ, so none were drawn.")
    if no_direction:
        no_direction.sort(key=surveys.natural_key)
        arcpy.AddMessage(
            f"No direction in the name, so no line for: {', '.join(no_direction)}"
        )
    return len(features)


def _lines_from_kmz(in_points):
    """The transect lines Step 1 saved from the KMZ next to the points, as
    [(name, geometry)]. Empty when there are none."""
    with gis.carry_on("read the transect lines from the KMZ",
                      so="every transect point gets a drawn line"):
        folder = os.path.dirname(arcpy.Describe(in_points).catalogPath)
        path = os.path.join(folder, surveys.TRANSECT_LINES_FROM_KMZ)
        if not arcpy.Exists(path):
            return []
        with arcpy.da.SearchCursor(path, [_name_field(path), "SHAPE@"]) as rows:
            return [((name or "").strip(), geometry)
                    for name, geometry in rows if geometry is not None]
    return []


def _xy(point):
    return point.X, point.Y


def _name_field(dataset):
    for field in arcpy.ListFields(dataset):
        if field.name.lower() == "name":
            return field.name
    raise surveys.SurveyMapError(
        "The transect points need a Name field holding names like 'T201 S 2m'."
    )
