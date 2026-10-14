# -*- coding: utf-8 -*-
"""Reading the direction out of a transect name, and working out where a line
in that direction ends. No arcpy here.

Transect names hold the transect ID, then a compass direction and usually the
depth, for example 'T201 S 2m' or 'T204 NE 3m'.
"""

import math
import re

COMPASS_POINTS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)

# Compass point -> bearing in degrees, clockwise from north.
BEARINGS = {point: index * 22.5 for index, point in enumerate(COMPASS_POINTS)}

_WORDS = {"NORTH": "N", "EAST": "E", "SOUTH": "S", "WEST": "W"}

# A compass point on its own, or run into the depth as in 'S2m' or 'NE3.5m'.
_POINT_TOKEN = re.compile(
    r"^(" + "|".join(sorted(COMPASS_POINTS, key=len, reverse=True)) + r")"
    r"(\d+(\.\d+)?M?)?$"
)
_SEPARATORS = re.compile(r"[\s_,;:/()\[\]-]+")


def _word_point(token):
    """'NORTH' -> 'N', 'SOUTHEAST' -> 'SE', anything else -> None."""
    if token in _WORDS:
        return _WORDS[token]
    for first in ("NORTH", "SOUTH"):
        rest = token[len(first):]
        if token.startswith(first) and rest in ("EAST", "WEST"):
            return _WORDS[first] + _WORDS[rest]
    return None


def parse_direction(name):
    """The bearing named in a transect name, in degrees clockwise from north,
    or None if the name has no direction.

    The first word is the transect's own ID ('T201'), so it is never read as a
    direction.
    """
    if not name:
        return None
    tokens = [
        token.upper().strip(".")
        for token in _SEPARATORS.split(str(name).strip())
        if token
    ]
    rest = tokens[1:]
    for index, token in enumerate(rest):
        following = rest[index + 1] if index + 1 < len(rest) else ""
        if token in ("NORTH", "SOUTH") and following in ("EAST", "WEST"):
            return BEARINGS[_WORDS[token] + _WORDS[following]]
        match = _POINT_TOKEN.match(token)
        if match:
            return BEARINGS[match.group(1)]
        point = _word_point(token)
        if point:
            return BEARINGS[point]
    return None


def offset(x, y, bearing, distance):
    """The point `distance` away from (x, y) on `bearing` (degrees clockwise
    from north), in the same projected units as x and y."""
    angle = math.radians(bearing)
    return x + distance * math.sin(angle), y + distance * math.cos(angle)
