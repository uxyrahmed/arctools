# -*- coding: utf-8 -*-
"""Names and settings the Currents Map tools share. No arcpy here."""

import ntpath
import os
import re


class CurrentsMapError(Exception):
    """A problem the person running the tool can fix, with a message saying how."""


# Current points are named with this prefix, like 'C1 start' and 'C1 end'.
CURRENT_PREFIX = "C"

# --- Data -------------------------------------------------------------------

# Feature classes the tools write in the geodatabase.
ARROWS_FEATURE_CLASS = "C_Arrows"
POINTS_FEATURE_CLASS = "C_Points"

# Layer names in the map (also the legend text).
ARROWS_LAYER_NAME = "Currents"
POINTS_LAYER_NAME = "Currents Survey Points"

# Decimal places in the speed labels, in metres per second.
SPEED_DECIMALS = 2

# Decimal places kept in X and Y: centimetres in a projected coordinate
# system, about 10 cm in degrees.
XY_DECIMALS = 2
XY_DECIMALS_DEGREES = 6

# Default coordinate system to measure in, and for X and Y: WGS 1984 UTM
# Zone 43N north of the equator, 43S south of it.
UTM_NORTH_WKID = 32643
UTM_SOUTH_WKID = 32743

# --- Look -------------------------------------------------------------------

# Labels: white Tahoma with a black halo, like the Survey Location Map.
LABEL_FONT = "Tahoma"
LABEL_FONT_STYLE = "Regular"
LABEL_SIZE_PT = 12
LABEL_COLOR = (255, 255, 255)
HALO_COLOR = (0, 0, 0)
HALO_SIZE_PT = 2

# Arrows: white with a black edge. Restyle the Currents layer in the map to
# change it; the tools keep a layer's style once it's there.
ARROW_COLOR = (255, 255, 255)
ARROW_EDGE_COLOR = (0, 0, 0)
ARROW_WIDTH_PT = 1.5
ARROW_EDGE_PT = 0.75
ARROWHEAD_SIZE_PT = 9

# Start and end points, when shown: small black-edged white circles.
POINT_SIZE_PT = 5

# Space left around the currents when zooming to them, as a share of their
# extent (0.25 = a quarter more on every side).
ZOOM_MARGIN = 0.25
# Smallest width zoomed to, in metres, so one short current isn't filling the map.
MIN_ZOOM_WIDTH_M = 200.0

_PREFIX = re.compile(r"\s*([A-Za-z]+)")


def name_prefix(name):
    """The letters a point name starts with, in capitals: 'C1 start' -> 'C'."""
    if name is None:
        return ""
    match = _PREFIX.match(str(name))
    return match.group(1).upper() if match else ""


def normalise(name):
    """Name used for matching: case and extra spaces don't matter."""
    return " ".join(str(name or "").split()).casefold()


def natural_key(name):
    """Sort key that puts 'C2' before 'C10'."""
    parts = re.split(r"(\d+)", str(name or ""))
    return [int(part) if index % 2 else part.casefold() for index, part in enumerate(parts)]


def gdb_name_for(csv_path):
    """A geodatabase name based on the CSV file name.

    'Ungoofaaru currents 15-10.csv' -> 'Ungoofaaru_currents_15_10'
    """
    # ntpath splits on both kinds of slash, whichever the path uses.
    base = os.path.splitext(ntpath.basename(str(csv_path)))[0]
    name = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_")
    if not name:
        return "Currents_Data"
    if not name[0].isalpha():
        name = "Currents_" + name
    return name


def plural(count, noun):
    """'1 point', '2 points'."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def utm_wkid(latitude):
    """Default UTM zone for data at this latitude."""
    return UTM_NORTH_WKID if latitude >= 0 else UTM_SOUTH_WKID


def zoom_extent(xmin, ymin, xmax, ymax, metres_per_unit=1.0):
    """The extent to zoom to so the currents fill the map with some space
    around them: (xmin, ymin, xmax, ymax), never narrower than
    MIN_ZOOM_WIDTH_M across."""
    width, height = xmax - xmin, ymax - ymin
    smallest = MIN_ZOOM_WIDTH_M / metres_per_unit
    margin = max(width, height) * ZOOM_MARGIN
    half_w = max(width / 2 + margin, smallest / 2)
    half_h = max(height / 2 + margin, smallest / 2)
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    return cx - half_w, cy - half_h, cx + half_w, cy + half_h
