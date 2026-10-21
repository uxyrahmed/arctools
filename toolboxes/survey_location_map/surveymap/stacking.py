# -*- coding: utf-8 -*-
"""Page geometry for the layout: how tall a table needs to be, and where each
heading and table goes when they are stacked inside the tables panel.
No arcpy here; everything is in page units unless a name says points.
"""

import math
from collections import namedtuple

# Height of a line of text as a multiple of its font size.
LINE_HEIGHT = 1.2

# Extra room added to each table so rounding never pushes ArcGIS Pro into
# shrinking the text or splitting the table into columns.
TABLE_PADDING = 1.04
TABLE_PADDING_PT = 2.0

# The smallest a table may be squeezed to, as a share of its full height,
# when the tables don't fit in the panel.
MIN_SCALE = 0.25

# Anchor name (as ArcGIS Pro stores it) -> where the anchor sits on the
# element, as a share of its width and height from the bottom left corner.
ANCHORS = {
    "BottomLeftCorner": (0.0, 0.0),
    "BottomMidPoint": (0.5, 0.0),
    "BottomRightCorner": (1.0, 0.0),
    "LeftMidPoint": (0.0, 0.5),
    "CenterPoint": (0.5, 0.5),
    "RightMidPoint": (1.0, 0.5),
    "TopLeftCorner": (0.0, 1.0),
    "TopMidPoint": (0.5, 1.0),
    "TopRightCorner": (1.0, 1.0),
}

POINTS_PER_UNIT = {
    "INCH": 72.0,
    "CENTIMETER": 72.0 / 2.54,
    "MILLIMETER": 72.0 / 25.4,
    "POINT": 1.0,
}

# One heading and its table. A block with no heading has heading_height 0.
Block = namedtuple("Block", "heading_width heading_height table_width table_height")

# Where a block goes: heading is (left, bottom) or None, table is
# (left, bottom, width, height).
Placement = namedtuple("Placement", "heading table")


def points_per_unit(page_units):
    try:
        return POINTS_PER_UNIT[str(page_units).upper()]
    except KeyError:
        raise ValueError(f"Unknown page units: {page_units}")


def anchor_point(anchor, left, bottom, width, height):
    """Position of an element's anchor when its box starts at (left, bottom)."""
    fx, fy = ANCHORS.get(anchor, (0.0, 0.0))
    return left + fx * width, bottom + fy * height


def box_corner(anchor, x, y, width, height):
    """Bottom left corner of an element whose anchor is at (x, y)."""
    fx, fy = ANCHORS.get(anchor, (0.0, 0.0))
    return x - fx * width, y - fy * height


def table_height_points(rows, text_size, heading_size=None, vertical_gap=0.0,
                        row_gap=0.0, heading_gap=0.0, show_headings=True,
                        columns=1):
    """Height in points a table frame needs to show `rows` rows at full size."""
    heading_size = text_size if heading_size is None else heading_size
    columns = max(int(columns or 1), 1)
    rows = int(math.ceil(max(rows, 0) / float(columns)))
    row = text_size * LINE_HEIGHT + 2 * vertical_gap
    height = rows * row + max(rows - 1, 0) * row_gap
    if show_headings:
        height += heading_size * LINE_HEIGHT + 2 * vertical_gap + heading_gap
    return height * TABLE_PADDING + TABLE_PADDING_PT


def stack(panel, blocks, margin=0.0, heading_gap=0.0, group_gap=0.0,
          min_gap=0.0, spread=False):
    """Stack blocks top to bottom inside panel, each centred across it.

    panel: (x_min, y_min, x_max, y_max).
    spread: False stacks them from the top, group_gap apart; True spaces them
        evenly down the whole panel.
    If the blocks don't fit even min_gap apart, every table is squeezed by the
    same factor (but not below MIN_SCALE) and they are stacked from the top.

    Returns (placements, scale) with one placement per block, in order.
    """
    if not blocks:
        return [], 1.0
    x_min, y_min, x_max, y_max = panel
    top = y_max - margin
    available = (y_max - y_min) - 2 * margin
    count = len(blocks)

    headings = sum(b.heading_height + heading_gap for b in blocks if b.heading_height)
    tables = sum(b.table_height for b in blocks)
    gaps = count - 1

    scale = 1.0
    if headings + tables + gaps * min_gap > available and tables > 0:
        room = available - headings - gaps * min_gap
        scale = max(room / tables, MIN_SCALE)
    heights = [b.table_height * scale for b in blocks]
    free = available - headings - sum(heights)

    if scale < 1.0:
        start, gap = 0.0, min_gap
    elif spread:
        gap = free / (count + 1)
        start = gap
        if gaps and gap < min_gap:
            # Not enough room for gaps above and below too: use it all between.
            start, gap = 0.0, free / gaps
    else:
        gap = group_gap
        if gaps and free < gaps * group_gap:
            gap = free / gaps
        start = 0.0

    centre = (x_min + x_max) / 2.0
    y = top - start
    placements = []
    for block, height in zip(blocks, heights):
        heading = None
        if block.heading_height:
            y -= block.heading_height
            heading = (centre - block.heading_width / 2.0, y)
            y -= heading_gap
        y -= height
        table = (centre - block.table_width / 2.0, y, block.table_width, height)
        placements.append(Placement(heading, table))
        y -= gap
    return placements, scale
