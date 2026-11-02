# -*- coding: utf-8 -*-
"""Compass directions: naming the direction a current went. No arcpy here."""

import math

COMPASS_POINTS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)


def compass_point(bearing):
    """The nearest of the 16 compass points to a bearing in degrees:
    181 -> 'S', 103 -> 'ESE'."""
    return COMPASS_POINTS[int(math.floor((bearing % 360.0) / 22.5 + 0.5)) % 16]


def bearing_to(dx, dy):
    """Bearing in degrees clockwise from north, from 0 up to 360, of a line
    going dx east and dy north."""
    return math.degrees(math.atan2(dx, dy)) % 360.0
