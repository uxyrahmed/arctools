# -*- coding: utf-8 -*-
"""The survey types the Survey Location Map tools know about, and the settings
that tie them to the KMZ and to the master layout.

To add a survey, add a line to SURVEYS and the matching layer, table and
heading to the master layout (see README.md). No arcpy here.
"""

import os
import re
from collections import namedtuple

POINT = "POINT"
POLYLINE = "POLYLINE"


class SurveyMapError(Exception):
    """A problem the person running the tool can fix, with a message saying how."""


class Survey(namedtuple("Survey", "code layer_name geometry prefixes feature_class")):
    """One survey type.

    code: short code, used in the layout's table and heading names.
    layer_name: name of the layer in the master layout (also the legend text).
    geometry: POINT or POLYLINE.
    prefixes: name prefixes that mark this survey's features in the KMZ. Empty
        for layers the tools make themselves, like transect lines.
    feature_class: name of the feature class the tools write.
    """

    __slots__ = ()

    @property
    def is_point(self):
        return self.geometry == POINT

    @property
    def table_name(self):
        """Name of this survey's table frame in the layout (point surveys only)."""
        return f"{self.code} Table" if self.is_point else None

    @property
    def heading_name(self):
        """Name of the text element above this survey's table (point surveys only)."""
        return f"{self.code} Heading" if self.is_point else None


SURVEYS = (
    Survey("SW", "Sea Water Sampling Points", POINT, ("SW",), "SW_Points"),
    Survey("VSS", "Visual Snorkelling Survey Points", POINT, ("VSS",), "VSS_Points"),
    Survey("VSS_LINES", "Visual Snorkelling Survey Lines", POLYLINE, ("VSS",), "VSS_Lines"),
    Survey("T", "Marine Transects", POINT, ("T",), "T_Points"),
    Survey("T_LINES", "Transect Line", POLYLINE, (), "T_Lines"),
    Survey("BP", "Beach Profiles", POINT, ("BP", "P"), "BP_Points"),
    Survey("GW", "Ground Water Sampling Points", POINT, ("GW",), "GW_Points"),
    Survey("C", "Currents Survey Points", POINT, ("C",), "C_Points"),
    Survey("N", "Noise Survey Points", POINT, ("N",), "N_Points"),
)

# Transect points, and the lines drawn from them.
TRANSECT_POINTS = "T"
TRANSECT_LINES = "T_LINES"

# --- Data -------------------------------------------------------------------

# Default length of a transect line, in metres.
TRANSECT_LENGTH_M = 50.0

# Decimal places kept in the X and Y fields, and shown in the tables:
# centimetres in a projected coordinate system, about 10 cm in degrees.
XY_DECIMALS = 2
XY_DECIMALS_DEGREES = 6

# Default coordinate system for X and Y, and for drawing transect lines:
# WGS 1984 UTM Zone 43N north of the equator, 43S south of it.
UTM_NORTH_WKID = 32643
UTM_SOUTH_WKID = 32743

# --- Point labels -----------------------------------------------------------

LABEL_FONT = "Tahoma"
LABEL_FONT_STYLE = "Regular"
LABEL_SIZE_PT = 12
LABEL_COLOR = (255, 255, 255)
HALO_COLOR = (0, 0, 0)
HALO_SIZE_PT = 2

# --- Layout -----------------------------------------------------------------

# Rectangle in the layout that the tables are stacked inside.
TABLES_PANEL_NAME = "Tables Panel"

# Spacing used when stacking the tables, in points (72 points = 1 inch).
PANEL_MARGIN_PT = 6.0
HEADING_GAP_PT = 3.0
GROUP_GAP_PT = 14.0
MIN_GAP_PT = 4.0

_PREFIX = re.compile(r"\s*([A-Za-z]+)")


def name_prefix(name):
    """The letters a feature name starts with, in capitals.

    'SW201' -> 'SW', 'T201 S 2m' -> 'T', 'C202 start' -> 'C', '12' -> ''.
    """
    if name is None:
        return ""
    match = _PREFIX.match(str(name))
    return match.group(1).upper() if match else ""


def survey_for(name, geometry):
    """The survey a KMZ feature belongs to, from its name and geometry, or None."""
    prefix = name_prefix(name)
    if not prefix:
        return None
    for survey in SURVEYS:
        if survey.geometry == geometry and prefix in survey.prefixes:
            return survey
    return None


def by_code(code):
    for survey in SURVEYS:
        if survey.code == code:
            return survey
    raise KeyError(code)


def point_surveys():
    return [survey for survey in SURVEYS if survey.is_point]


def normalise(name):
    """Name used for matching layers and layout elements: case and extra
    spaces don't matter."""
    return " ".join(str(name or "").split()).casefold()


def unknown_feature_class(prefix):
    """Feature class name for points whose prefix isn't a known survey."""
    return f"{prefix}_Points"


def natural_key(name):
    """Sort key that puts 'P2' before 'P10'."""
    parts = re.split(r"(\d+)", str(name or ""))
    return [int(part) if index % 2 else part.casefold() for index, part in enumerate(parts)]


def gdb_name_for(kmz_path):
    """A geodatabase name based on the KMZ file name.

    'Masterplan changes surveyed 2.kmz' -> 'Masterplan_changes_surveyed_2'
    """
    base = os.path.splitext(os.path.basename(str(kmz_path)))[0]
    name = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_")
    if not name:
        return "Survey_Data"
    if not name[0].isalpha():
        name = "Survey_" + name
    return name


def plural(count, noun):
    """'1 point', '2 points'."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def utm_wkid(latitude):
    """Default UTM zone for data at this latitude."""
    return UTM_NORTH_WKID if latitude >= 0 else UTM_SOUTH_WKID
