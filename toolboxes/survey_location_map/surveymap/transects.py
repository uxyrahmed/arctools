# -*- coding: utf-8 -*-
"""Step 2: draw a line from each transect point in the direction its name gives."""

import arcpy

from . import directions, gis, surveys


def draw_transect_lines(in_points, out_lines, length_m=surveys.TRANSECT_LENGTH_M,
                        coordinate_system=None):
    """Draw a line length_m long from each point in in_points, in the compass
    direction in its name ('T201 S 2m' goes south). Points with no direction in
    their name get no line.

    Lines are worked out in coordinate_system if it is projected, otherwise in
    WGS 1984 UTM Zone 43N (or 43S south of the equator), and saved in the
    points' own coordinate system. Returns the number of lines drawn.
    """
    if length_m is None or length_m <= 0:
        raise surveys.SurveyMapError("The line length must be more than 0 metres.")

    source_sr = arcpy.Describe(in_points).spatialReference
    name_field = _name_field(in_points)
    with arcpy.da.SearchCursor(in_points, [name_field, "SHAPE@"]) as rows:
        points = [(name or "", geometry) for name, geometry in rows if geometry is not None]

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

    lines = []
    no_direction = []
    for name, geometry in points:
        bearing = directions.parse_direction(name)
        if bearing is None:
            no_direction.append(name or "(no name)")
            continue
        start = gis.project(geometry, work_sr).firstPoint
        end_x, end_y = directions.offset(start.X, start.Y, bearing, distance)
        line = arcpy.Polyline(
            arcpy.Array([arcpy.Point(start.X, start.Y), arcpy.Point(end_x, end_y)]),
            work_sr,
        )
        lines.append((name, gis.project(line, source_sr)))
    lines.sort(key=lambda feature: surveys.natural_key(feature[0]))

    gis.write_features(out_lines, surveys.POLYLINE, source_sr, lines)

    arcpy.AddMessage(
        f"Drew {surveys.plural(len(lines), 'transect line')}, {length_m:g} m long, "
        f"worked out in {gis.describe_spatial_reference(work_sr)}."
    )
    if no_direction:
        no_direction.sort(key=surveys.natural_key)
        arcpy.AddMessage(
            f"No direction in the name, so no line for: {', '.join(no_direction)}"
        )
    return len(lines)


def _name_field(dataset):
    for field in arcpy.ListFields(dataset):
        if field.name.lower() == "name":
            return field.name
    raise surveys.SurveyMapError(
        "The transect points need a Name field holding names like 'T201 S 2m'."
    )
