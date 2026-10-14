# -*- coding: utf-8 -*-
"""Tests for surveymap.stacking. Run from the repository root with:

    python -m unittest discover -s toolboxes/survey_location_map/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from surveymap import stacking  # noqa: E402
from surveymap.stacking import Block  # noqa: E402

# A tables panel like the one in the Funadhoo example, in inches.
PANEL = (10.95, 0.15, 13.37, 8.34)


def block(rows, heading=True, width=1.8):
    """A heading and a table with `rows` rows of 8 pt text, in inches. The
    tables in the Funadhoo example have about this row height."""
    height = stacking.table_height_points(rows, 8.0, vertical_gap=1.0) / 72.0
    return Block(1.6 if heading else 0.0, 0.17 if heading else 0.0, width, height)


class UnitTests(unittest.TestCase):
    def test_points_per_unit(self):
        self.assertEqual(stacking.points_per_unit("INCH"), 72.0)
        self.assertAlmostEqual(stacking.points_per_unit("Centimeter"), 72.0 / 2.54)
        self.assertAlmostEqual(stacking.points_per_unit("MILLIMETER"), 72.0 / 25.4)
        self.assertEqual(stacking.points_per_unit("POINT"), 1.0)
        with self.assertRaises(ValueError):
            stacking.points_per_unit("FURLONG")

    def test_anchor_round_trip(self):
        for anchor in stacking.ANCHORS:
            with self.subTest(anchor=anchor):
                x, y = stacking.anchor_point(anchor, 2.0, 3.0, 4.0, 1.0)
                self.assertEqual(stacking.box_corner(anchor, x, y, 4.0, 1.0), (2.0, 3.0))

    def test_anchor_points(self):
        self.assertEqual(stacking.anchor_point("BottomLeftCorner", 2, 3, 4, 1), (2, 3))
        self.assertEqual(stacking.anchor_point("TopLeftCorner", 2, 3, 4, 1), (2, 4))
        self.assertEqual(stacking.anchor_point("CenterPoint", 2, 3, 4, 1), (4, 3.5))
        self.assertEqual(stacking.anchor_point("RightMidPoint", 2, 3, 4, 1), (6, 3.5))
        # An anchor we don't know is treated as the bottom left corner.
        self.assertEqual(stacking.anchor_point(None, 2, 3, 4, 1), (2, 3))


class TableHeightTests(unittest.TestCase):
    def test_formula(self):
        row = 10 * stacking.LINE_HEIGHT + 2 * 2.0
        expected = (8 * row + row) * stacking.TABLE_PADDING + stacking.TABLE_PADDING_PT
        self.assertAlmostEqual(
            stacking.table_height_points(8, 10.0, vertical_gap=2.0), expected)

    def test_headings_can_be_off(self):
        with_headings = stacking.table_height_points(3, 10.0)
        without = stacking.table_height_points(3, 10.0, show_headings=False)
        self.assertAlmostEqual(
            with_headings - without, 10.0 * stacking.LINE_HEIGHT * stacking.TABLE_PADDING)

    def test_gaps(self):
        plain = stacking.table_height_points(4, 10.0)
        gapped = stacking.table_height_points(4, 10.0, row_gap=1.0, heading_gap=3.0)
        self.assertAlmostEqual(gapped - plain, (3 * 1.0 + 3.0) * stacking.TABLE_PADDING)

    def test_heading_size(self):
        small = stacking.table_height_points(2, 10.0, heading_size=10.0)
        big = stacking.table_height_points(2, 10.0, heading_size=14.0)
        self.assertAlmostEqual(big - small, 4.0 * stacking.LINE_HEIGHT * stacking.TABLE_PADDING)

    def test_columns_share_the_rows(self):
        self.assertAlmostEqual(
            stacking.table_height_points(7, 10.0, columns=2),
            stacking.table_height_points(4, 10.0),
        )
        self.assertAlmostEqual(
            stacking.table_height_points(7, 10.0, columns=0),
            stacking.table_height_points(7, 10.0),
        )

    def test_more_rows_are_taller(self):
        heights = [stacking.table_height_points(n, 10.0, vertical_gap=2.0) for n in range(12)]
        self.assertEqual(heights, sorted(heights))
        self.assertEqual(len(set(heights)), len(heights))

    def test_no_rows(self):
        self.assertGreater(stacking.table_height_points(0, 10.0), 0)
        self.assertAlmostEqual(
            stacking.table_height_points(0, 10.0, show_headings=False),
            stacking.TABLE_PADDING_PT,
        )


class StackTests(unittest.TestCase):
    margin, heading_gap, group_gap, min_gap = 6 / 72.0, 3 / 72.0, 14 / 72.0, 4 / 72.0

    def run_stack(self, blocks, panel=PANEL, spread=False):
        return stacking.stack(
            panel, blocks, margin=self.margin, heading_gap=self.heading_gap,
            group_gap=self.group_gap, min_gap=self.min_gap, spread=spread,
        )

    def assertInsidePanel(self, placements, blocks, panel=PANEL):
        x_min, y_min, x_max, y_max = panel
        for placement, b in zip(placements, blocks):
            left, bottom, width, height = placement.table
            self.assertGreaterEqual(left, x_min - 1e-9)
            self.assertLessEqual(left + width, x_max + 1e-9)
            self.assertGreaterEqual(bottom, y_min + self.margin - 1e-9)
            if placement.heading is not None:
                self.assertLessEqual(placement.heading[1] + b.heading_height,
                                     y_max - self.margin + 1e-9)

    def space_above(self, placements, blocks):
        """Space between the top margin and the first heading."""
        return (PANEL[3] - self.margin) - (placements[0].heading[1] + blocks[0].heading_height)

    def gaps_between(self, placements, blocks):
        """Space between the bottom of each table and the top of the next block."""
        gaps = []
        for above, below, b in zip(placements, placements[1:], blocks[1:]):
            top_of_next = (below.heading[1] + b.heading_height if below.heading
                           else below.table[1] + below.table[3])
            gaps.append(above.table[1] - top_of_next)
        return gaps

    def test_nothing_to_stack(self):
        self.assertEqual(stacking.stack(PANEL, []), ([], 1.0))

    def test_stack_from_top(self):
        blocks = [block(8), block(4), block(2), block(5), block(7)]
        placements, scale = self.run_stack(blocks)
        self.assertEqual(scale, 1.0)
        self.assertEqual(len(placements), len(blocks))
        self.assertInsidePanel(placements, blocks)
        # The first heading sits just under the top margin.
        first = placements[0]
        self.assertAlmostEqual(first.heading[1] + blocks[0].heading_height,
                               PANEL[3] - self.margin)
        for gap in self.gaps_between(placements, blocks):
            self.assertAlmostEqual(gap, self.group_gap)

    def test_heading_sits_above_its_table(self):
        blocks = [block(3), block(6)]
        placements, _ = self.run_stack(blocks)
        for placement in placements:
            table_top = placement.table[1] + placement.table[3]
            self.assertAlmostEqual(placement.heading[1] - table_top, self.heading_gap)

    def test_blocks_are_centred_across_the_panel(self):
        blocks = [block(3, width=1.2), block(3, width=2.0)]
        placements, _ = self.run_stack(blocks)
        centre = (PANEL[0] + PANEL[2]) / 2
        for placement, b in zip(placements, blocks):
            left, _, width, _ = placement.table
            self.assertAlmostEqual(left + width / 2, centre)
            self.assertAlmostEqual(placement.heading[0] + b.heading_width / 2, centre)

    def test_order_is_kept(self):
        blocks = [block(2), block(9), block(1)]
        placements, _ = self.run_stack(blocks)
        bottoms = [p.table[1] for p in placements]
        self.assertEqual(bottoms, sorted(bottoms, reverse=True))

    def test_table_heights_are_kept_when_they_fit(self):
        blocks = [block(8), block(4)]
        placements, _ = self.run_stack(blocks)
        for placement, b in zip(placements, blocks):
            self.assertAlmostEqual(placement.table[3], b.table_height)

    def test_spread_evenly(self):
        blocks = [block(3), block(2)]
        placements, scale = self.run_stack(blocks, spread=True)
        self.assertEqual(scale, 1.0)
        top_space = self.space_above(placements, blocks)
        bottom_space = placements[-1].table[1] - (PANEL[1] + self.margin)
        (between,) = self.gaps_between(placements, blocks)
        self.assertAlmostEqual(top_space, between)
        self.assertAlmostEqual(bottom_space, between)

    def test_spread_single_block_is_centred_down_the_panel(self):
        blocks = [block(4)]
        placements, _ = self.run_stack(blocks, spread=True)
        top_space = self.space_above(placements, blocks)
        bottom_space = placements[0].table[1] - (PANEL[1] + self.margin)
        self.assertAlmostEqual(top_space, bottom_space)

    def test_spread_with_little_room_uses_it_all_between(self):
        # Fits, but gaps above and below as well would be under the minimum.
        blocks = [block(4), block(4), block(4)]
        needed = sum(b.heading_height + self.heading_gap + b.table_height for b in blocks)
        panel = (0.0, 0.0, 3.0, needed + 2 * self.margin + 3 * self.min_gap)
        placements, scale = self.run_stack(blocks, panel=panel, spread=True)
        self.assertEqual(scale, 1.0)
        self.assertAlmostEqual(placements[0].heading[1] + blocks[0].heading_height,
                               panel[3] - self.margin)
        self.assertAlmostEqual(placements[-1].table[1], self.margin)
        for gap in self.gaps_between(placements, blocks):
            self.assertAlmostEqual(gap, 1.5 * self.min_gap)

    def test_from_top_closes_up_gaps_when_short_of_room(self):
        blocks = [block(4), block(4), block(4)]
        needed = sum(b.heading_height + self.heading_gap + b.table_height for b in blocks)
        panel = (0.0, 0.0, 3.0, needed + 2 * self.margin + 2 * self.min_gap + 0.01)
        placements, scale = self.run_stack(blocks, panel=panel)
        self.assertEqual(scale, 1.0)
        self.assertInsidePanel(placements, blocks, panel)
        for gap in self.gaps_between(placements, blocks):
            self.assertLess(gap, self.group_gap)
            self.assertGreaterEqual(gap, self.min_gap)

    def test_overflow_squeezes_tables_to_fit(self):
        blocks = [block(15), block(12), block(10), block(14), block(12)]
        placements, scale = self.run_stack(blocks)
        self.assertLess(scale, 1.0)
        self.assertGreaterEqual(scale, stacking.MIN_SCALE)
        self.assertInsidePanel(placements, blocks)
        self.assertAlmostEqual(placements[-1].table[1], PANEL[1] + self.margin)
        for placement, b in zip(placements, blocks):
            self.assertAlmostEqual(placement.table[3], b.table_height * scale)
        for gap in self.gaps_between(placements, blocks):
            self.assertAlmostEqual(gap, self.min_gap)

    def test_overflow_never_squeezes_below_the_minimum(self):
        blocks = [block(200)] * 4
        placements, scale = self.run_stack(blocks)
        self.assertEqual(scale, stacking.MIN_SCALE)
        # It can't fit, so the last table runs past the bottom of the panel.
        self.assertLess(placements[-1].table[1], PANEL[1])

    def test_block_without_heading(self):
        blocks = [block(3, heading=False), block(3)]
        placements, _ = self.run_stack(blocks)
        self.assertIsNone(placements[0].heading)
        self.assertAlmostEqual(placements[0].table[1] + placements[0].table[3],
                               PANEL[3] - self.margin)
        self.assertIsNotNone(placements[1].heading)

    def test_funadhoo_tables_fit_at_full_size(self):
        # The five tables in the Funadhoo example: SW 8, C 4, T 2, VSS 5, BP 7 rows.
        blocks = [block(8), block(4), block(2), block(5), block(7)]
        placements, scale = self.run_stack(blocks)
        self.assertEqual(scale, 1.0)
        self.assertGreater(placements[-1].table[1], PANEL[1])


if __name__ == "__main__":
    unittest.main()
