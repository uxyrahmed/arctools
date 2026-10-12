# -*- coding: utf-8 -*-
"""Tests for callout_layout. Run from the repository root with:

    python -m unittest discover -s toolboxes/pictorial_maps/tests
"""

import io
import itertools
import math
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import callout_layout as cl  # noqa: E402

# The sample photos in data/images, in WGS 1984 UTM Zone 43N metres.
SAMPLE_PHOTOS = [
    ("eroded 1", (310897.3, 680348.6)),
    ("eroded 2", (310870.3, 680391.3)),
    ("veg 1", (310897.3, 680312.4)),
    ("veg 2", (310903.2, 680299.8)),
    ("veg 3", (310895.8, 680280.7)),
    ("veg 4", (310899.2, 680271.5)),
    ("veg 5", (310889.0, 680257.4)),
    ("veg 6", (310886.2, 680254.3)),
    ("veg 7", (310886.2, 680210.1)),
    ("veg 8", (310881.9, 680198.1)),
]


def portrait_sizes(count, scale=1000.0, height_pt=90.0):
    h = cl.page_points_to_map_units(height_pt, scale)
    return [(h * 0.75, h)] * count


class LayoutChecks:
    """Assertions shared by the layout tests."""

    def assert_good_layout(self, anchors, sizes, centres):
        self.assertEqual(len(centres), len(anchors))
        self.assertFalse(cl.images_overlap(centres, sizes),
                         "images overlap each other")
        for (x, y), (w, h) in zip(centres, sizes):
            for ax, ay in anchors:
                covered = abs(ax - x) < w / 2 and abs(ay - y) < h / 2
                self.assertFalse(covered, "an image covers a photo point")

    def count_crossings(self, anchors, centres):
        crossings = 0
        for i in range(len(anchors)):
            for j in range(i + 1, len(anchors)):
                if cl.segments_cross(anchors[i], centres[i],
                                     anchors[j], centres[j]):
                    crossings += 1
        return crossings


class TestUnits(unittest.TestCase):
    def test_one_inch_at_1_to_1000_is_25_4_metres(self):
        self.assertAlmostEqual(cl.page_points_to_map_units(72, 1000), 25.4)

    def test_feet_units(self):
        self.assertAlmostEqual(
            cl.page_points_to_map_units(72, 1000, 0.3048), 25.4 / 0.3048)

    def test_utm_zone(self):
        self.assertEqual(cl.utm_wkid(73.29, 6.15), 32643)  # Maldives
        self.assertEqual(cl.utm_wkid(-0.1, 51.5), 32630)  # London
        self.assertEqual(cl.utm_wkid(151.2, -33.9), 32756)  # Sydney
        self.assertEqual(cl.utm_wkid(180.0, 0.0), 32660)
        self.assertEqual(cl.utm_wkid(-180.0, -1.0), 32701)

    def test_image_attachment(self):
        self.assertTrue(cl.is_image_attachment("IMG_0168.jpg", None))
        self.assertTrue(cl.is_image_attachment("x", "image/jpeg"))
        self.assertTrue(cl.is_image_attachment("A.JPEG", ""))
        self.assertFalse(cl.is_image_attachment("notes.pdf",
                                                "application/pdf"))


class TestSpread(unittest.TestCase):
    def test_leaves_spaced_values_alone(self):
        self.assertEqual(cl.spread([0, 5, 10], [2, 2]), [0, 5, 10])

    def test_pushes_a_clump_apart_evenly(self):
        result = cl.spread([5, 5, 5], [2, 2])
        for got, want in zip(result, [3, 5, 7]):
            self.assertAlmostEqual(got, want)

    def test_only_moves_the_crowded_part(self):
        result = cl.spread([0, 10, 10.5, 30], [2, 2, 2])
        self.assertAlmostEqual(result[0], 0)
        self.assertAlmostEqual(result[1], 9.25)
        self.assertAlmostEqual(result[2], 11.25)
        self.assertAlmostEqual(result[3], 30)

    def test_uneven_gaps(self):
        result = cl.spread([0, 0], [4])
        self.assertAlmostEqual(result[1] - result[0], 4)
        self.assertAlmostEqual(sum(result), 0)

    def test_single_value(self):
        self.assertEqual(cl.spread([3.0], []), [3.0])


class TestAround(unittest.TestCase, LayoutChecks):
    def test_sample_photos(self):
        anchors = [xy for _, xy in SAMPLE_PHOTOS]
        for scale in (300, 1000, 2500):
            sizes = portrait_sizes(len(anchors), scale)
            centres = cl.arrange_images(anchors, sizes, cl.AROUND)
            self.assert_good_layout(anchors, sizes, centres)
            self.assertEqual(self.count_crossings(anchors, centres), 0,
                             "leaders cross at 1:{}".format(scale))

    def test_single_photo(self):
        anchors = [(100.0, 200.0)]
        sizes = portrait_sizes(1)
        centres = cl.arrange_images(anchors, sizes, cl.AROUND)
        self.assert_good_layout(anchors, sizes, centres)
        # A lone photo gets its image directly above it.
        self.assertAlmostEqual(centres[0][0], 100.0, places=3)
        self.assertGreater(centres[0][1], 200.0)

    def test_photos_at_the_same_spot(self):
        anchors = [(0.0, 0.0)] * 6
        sizes = portrait_sizes(6)
        centres = cl.arrange_images(anchors, sizes, cl.AROUND)
        self.assert_good_layout(anchors, sizes, centres)

    def test_many_random_photos(self):
        rng = random.Random(7)
        for count in (2, 5, 25, 120):
            anchors = [(rng.uniform(0, 300), rng.uniform(0, 120))
                       for _ in range(count)]
            sizes = portrait_sizes(count, 1000, 60)
            for arrangement in cl.ARRANGEMENTS:
                centres = cl.arrange_images(
                    anchors, sizes, arrangement,
                    extent=(-1000, -1000, 1300, 1120))
                self.assert_good_layout(anchors, sizes, centres)
                self.assertEqual(self.count_crossings(anchors, centres), 0)

    def test_mixed_orientations(self):
        rng = random.Random(3)
        anchors = [(rng.uniform(0, 50), rng.uniform(0, 400))
                   for _ in range(12)]
        h = cl.page_points_to_map_units(90, 1000)
        sizes = [(h * 0.75, h) if i % 2 else (h * 1.33, h)
                 for i in range(12)]
        centres = cl.arrange_images(anchors, sizes, cl.AROUND)
        self.assert_good_layout(anchors, sizes, centres)

    def test_images_stay_near_their_photos(self):
        # Two well separated groups: each image should land on its own side.
        anchors = [(0.0, 0.0), (0.0, 10.0), (1000.0, 0.0), (1000.0, 10.0)]
        sizes = portrait_sizes(4, 500)
        centres = cl.arrange_images(anchors, sizes, cl.AROUND)
        self.assertLess(centres[0][0], 500)
        self.assertLess(centres[1][0], 500)
        self.assertGreater(centres[2][0], 500)
        self.assertGreater(centres[3][0], 500)


def inside(extent, centre, size):
    (x, y), (w, h) = centre, size
    xmin, ymin, xmax, ymax = extent
    return (xmin <= x - w / 2 and x + w / 2 <= xmax and
            ymin <= y - h / 2 and y + h / 2 <= ymax)


class TestEdges(unittest.TestCase, LayoutChecks):
    def check(self, anchors, sizes, extent):
        centres = cl.arrange_images(anchors, sizes, cl.EDGES, extent=extent)
        self.assert_good_layout(anchors, sizes, centres)
        self.assertEqual(self.count_crossings(anchors, centres), 0)
        for centre, size in zip(centres, sizes):
            self.assertTrue(inside(extent, centre, size),
                            "an image is outside the map")
        return centres

    def test_sample_photos_in_a_view_around_them(self):
        anchors = [xy for _, xy in SAMPLE_PHOTOS]
        sizes = portrait_sizes(len(anchors), 1000)
        # A view about 7 x 9 inches at 1:1000, centred on the photos.
        extent = (310710, 680060, 310890 + 170, 680290 + 230)
        centres = self.check(anchors, sizes, extent)
        # All of them fit on the outer edge.
        slots = next(cl.edge_slots(extent, sizes[0], 0.2 * sizes[0][1]))[1]
        for centre in centres:
            self.assertIn(centre, slots)

    def test_many_photos_at_one_spot(self):
        # Like 45 photos of an eroded shore: most within a few metres, a few
        # along a lagoon, on a long thin island.
        rng = random.Random(1)
        anchors = [(rng.gauss(0, 15), rng.gauss(0, 15)) for _ in range(30)]
        anchors += [(rng.uniform(-150, 50), rng.uniform(100, 1300))
                    for _ in range(15)]
        extent = (-900, -500, 700, 1600)
        sizes = portrait_sizes(len(anchors), 5000, 60)
        self.check(anchors, sizes, extent)

    def test_fills_the_inside_edge_before_going_outside(self):
        anchors = [(0.0, 0.0)] * 30
        sizes = [(10.0, 10.0)] * 30
        extent = (-45.0, -45.0, 45.0, 45.0)
        centres = cl.arrange_images(anchors, sizes, cl.EDGES, gap=2.0,
                                    extent=extent)
        self.assert_good_layout(anchors, sizes, centres)
        inside_ring = next(cl.edge_slots(extent, (10.0, 10.0), 2.0))[1]
        self.assertEqual(len(inside_ring), 24)
        self.assertEqual(sum(1 for c in centres if c in inside_ring), 24)

    def test_photos_near_one_side_get_images_on_that_side(self):
        anchors = [(90.0, float(y)) for y in range(0, 100, 20)]
        sizes = [(10.0, 10.0)] * len(anchors)
        centres = self.check(anchors, sizes, (-100.0, -50.0, 120.0, 150.0))
        for x, _ in centres:
            self.assertGreater(x, 50)

    def test_mixed_orientations(self):
        rng = random.Random(5)
        anchors = [(rng.uniform(-50, 50), rng.uniform(-50, 50))
                   for _ in range(14)]
        sizes = [(7.5, 10.0) if i % 2 else (13.3, 10.0) for i in range(14)]
        self.check(anchors, sizes, (-120.0, -100.0, 120.0, 100.0))

    def test_overflow_goes_outside_the_map(self):
        # Room for 4 inside; the other 6 go in a ring just outside.
        extent = (-15.0, -15.0, 15.0, 15.0)
        anchors = [(0.0, 0.0)] * 10
        sizes = [(10.0, 10.0)] * 10
        self.assertEqual(cl.inside_edge_room(extent, sizes, 2.0), 4)
        centres = cl.arrange_images(anchors, sizes, cl.EDGES, gap=2.0,
                                    extent=extent)
        self.assertFalse(cl.images_overlap(centres, sizes))
        self.assertEqual(self.count_crossings(anchors, centres), 0)
        inside_count = sum(1 for c in centres
                           if inside(extent, c, (10.0, 10.0)))
        self.assertEqual(inside_count, 4)
        for x, y in centres:
            self.assertLess(max(abs(x), abs(y)), 15.0 + 2.0 + 10.0)

    def test_extent_smaller_than_one_image(self):
        sizes = [(10.0, 10.0)] * 3
        self.assertEqual(cl.inside_edge_room((0.0, 0.0, 5.0, 5.0), sizes), 0)
        centres = cl.arrange_images([(2.0, 2.0)] * 3, sizes, cl.EDGES,
                                    extent=(0.0, 0.0, 5.0, 5.0))
        self.assertFalse(cl.images_overlap(centres, sizes))

    def test_many_photos_never_fail(self):
        rng = random.Random(9)
        anchors = [(rng.gauss(0, 5), rng.gauss(0, 5)) for _ in range(150)]
        sizes = [(7.5, 10.0)] * 150
        centres = self.check_no_overlap(anchors, sizes, (-40, -40, 40, 40))
        self.assertEqual(self.count_crossings(anchors, centres), 0)

    def check_no_overlap(self, anchors, sizes, extent):
        centres = cl.arrange_images(anchors, sizes, cl.EDGES, extent=extent)
        self.assertFalse(cl.images_overlap(centres, sizes))
        return centres

    def test_needs_an_extent(self):
        with self.assertRaises(ValueError):
            cl.arrange_images([(0.0, 0.0)], [(1.0, 1.0)], cl.EDGES)


class TestEdgeSlots(unittest.TestCase):
    def rings(self, extent, size, count):
        return list(itertools.islice(cl.edge_slots(extent, size, 1.0),
                                     count))

    def test_inside_edge_room(self):
        extent = (-45.0, -45.0, 45.0, 45.0)
        sizes = [(10.0, 10.0)] * 3
        self.assertEqual(cl.inside_edge_room(extent, sizes, 2.0), 24)
        self.assertEqual(cl.inside_edge_room((0, 0, 5, 5), sizes, 2.0), 0)

    def test_slots_never_overlap(self):
        for extent, size in [((0, 0, 100, 60), (8, 10)),
                             ((0, 0, 30, 200), (8, 10)),
                             ((0, 0, 11, 12), (8, 10)),
                             ((0, 0, 500, 13), (8, 10)),
                             ((0, 0, 3, 3), (8, 10))]:
            slots = [slot for _, ring in self.rings(extent, size, 4)
                     for slot in ring]
            self.assertEqual(len(set(slots)), len(slots))
            self.assertFalse(cl.images_overlap(slots, [size] * len(slots)))

    def test_first_ring_is_inside_and_the_rest_outside(self):
        extent, size = (0, 0, 100, 60), (8, 10)
        rings = self.rings(extent, size, 3)
        self.assertEqual([number for number, _ in rings], [0, 1, 2])
        for slot in rings[0][1]:
            self.assertTrue(inside(extent, slot, size))
        for _, ring in rings[1:]:
            for x, y in ring:
                self.assertFalse(0 < x < 100 and 0 < y < 60)

    def test_no_inside_ring_when_nothing_fits_inside(self):
        rings = self.rings((0, 0, 3, 3), (8, 10), 2)
        self.assertEqual([number for number, _ in rings], [1, 2])

    def test_single_row_when_only_one_fits_vertically(self):
        number, ring = self.rings((0, 0, 100, 13), (8, 10), 1)[0]
        self.assertEqual(number, 0)
        self.assertEqual(len({y for _, y in ring}), 1)


class TestAssign(unittest.TestCase):
    def brute_force(self, costs):
        import itertools
        cols = range(len(costs[0]))
        return min(sum(costs[r][c] for r, c in enumerate(choice))
                   for choice in itertools.permutations(cols, len(costs)))

    def test_matches_brute_force(self):
        rng = random.Random(11)
        for _ in range(200):
            rows = rng.randint(1, 5)
            cols = rng.randint(rows, 6)
            costs = [[rng.uniform(0, 10) for _ in range(cols)]
                     for _ in range(rows)]
            chosen = cl.assign(costs)
            self.assertEqual(len(set(chosen)), rows)
            total = sum(costs[r][c] for r, c in enumerate(chosen))
            self.assertAlmostEqual(total, self.brute_force(costs))

    def test_more_rows_than_columns(self):
        with self.assertRaises(ValueError):
            cl.assign([[1.0], [2.0]])


class TestRowAbove(unittest.TestCase, LayoutChecks):
    def test_sample_photos(self):
        anchors = [xy for _, xy in SAMPLE_PHOTOS]
        sizes = portrait_sizes(len(anchors))
        centres = cl.arrange_images(anchors, sizes, cl.ROW_ABOVE)
        self.assert_good_layout(anchors, sizes, centres)
        self.assertEqual(self.count_crossings(anchors, centres), 0)
        top = max(y for _, y in anchors)
        for (x, y), (w, h) in zip(centres, sizes):
            self.assertGreater(y - h / 2, top)

    def test_spread_out_photos_stay_above_themselves(self):
        anchors = [(0.0, 0.0), (500.0, 0.0), (1000.0, 0.0)]
        sizes = portrait_sizes(3)
        centres = cl.arrange_images(anchors, sizes, cl.ROW_ABOVE)
        for (ax, _), (x, _) in zip(anchors, centres):
            self.assertAlmostEqual(ax, x)


class TestUncross(unittest.TestCase):
    def test_swaps_crossing_leaders(self):
        anchors = [(0.0, 0.0), (10.0, 0.0)]
        centres = [(10.0, 10.0), (0.0, 10.0)]
        sizes = [(1.0, 1.0)] * 2
        self.assertEqual(cl.uncross(anchors, sizes, centres),
                         [(0.0, 10.0), (10.0, 10.0)])

    def test_keeps_images_of_different_sizes(self):
        anchors = [(0.0, 0.0), (10.0, 0.0)]
        centres = [(10.0, 10.0), (0.0, 10.0)]
        sizes = [(1.0, 1.0), (2.0, 1.0)]
        self.assertEqual(cl.uncross(anchors, sizes, centres), centres)


class TestLongestLeader(unittest.TestCase):
    def test_longest(self):
        anchors = [(0.0, 0.0), (10.0, 0.0)]
        centres = [(3.0, 4.0), (10.0, 1.0)]
        self.assertAlmostEqual(cl.longest_leader(anchors, centres), 5.0)


class TestArguments(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(cl.arrange_images([], []), [])

    def test_mismatched_lengths(self):
        with self.assertRaises(ValueError):
            cl.arrange_images([(0, 0)], [])

    def test_unknown_arrangement(self):
        with self.assertRaises(ValueError):
            cl.arrange_images([(0, 0)], [(1, 1)], "SIDEWAYS")


class TestThumbnail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def sideways_photo_bytes(self):
        """A landscape JPEG tagged to be shown rotated, like a phone photo."""
        from PIL import Image
        photo = Image.new("RGB", (400, 300), (30, 120, 60))
        exif = Image.Exif()
        exif[0x0112] = 6  # Orientation: rotate 90 degrees clockwise
        buffer = io.BytesIO()
        photo.save(buffer, "JPEG", exif=exif.tobytes())
        return buffer.getvalue()

    def test_rotates_sideways_photo_upright(self):
        out = os.path.join(self.tmp.name, "thumb.png")
        width, height = cl.make_thumbnail(self.sideways_photo_bytes(), out,
                                          max_pixels=200)
        self.assertGreater(height, width)
        from PIL import Image
        with Image.open(out) as thumb:
            self.assertEqual(thumb.size, (width, height))
            self.assertNotIn(0x0112, thumb.getexif())

    def test_reads_from_file_and_limits_size(self):
        src = os.path.join(self.tmp.name, "photo.jpg")
        with open(src, "wb") as f:
            f.write(self.sideways_photo_bytes())
        out = os.path.join(self.tmp.name, "thumb.png")
        width, height = cl.make_thumbnail(src, out, max_pixels=100)
        # 100 px of photo plus the mat and edge on both sides.
        self.assertLessEqual(max(width, height), 100 + 2 * (3 + 1))

    def test_data_url(self):
        out = os.path.join(self.tmp.name, "thumb.png")
        cl.make_thumbnail(self.sideways_photo_bytes(), out)
        url = cl.image_data_url(out)
        self.assertTrue(url.startswith("data:image/png;base64,iVBORw0KGgo"))

    def photo_shape(self, aspect):
        """Width / height of the photo inside the thumbnail's frame."""
        out = os.path.join(self.tmp.name, "thumb.png")
        width, height = cl.make_thumbnail(self.sideways_photo_bytes(), out,
                                          max_pixels=200, aspect=aspect)
        frame = 2 * (max(3, round(200 * 0.03)) + 1)
        return (width - frame) / float(height - frame)

    def test_crops_a_portrait_photo_to_landscape(self):
        # The sample photo is 3:4 portrait once turned upright.
        self.assertAlmostEqual(self.photo_shape(4.0 / 3.0), 4.0 / 3.0,
                               places=1)

    def test_portrait_photo_stays_portrait(self):
        self.assertAlmostEqual(self.photo_shape(0.75), 0.75, places=1)
        self.assertAlmostEqual(self.photo_shape(None), 0.75, places=1)


class TestCropBox(unittest.TestCase):
    def test_portrait_to_landscape_keeps_the_middle(self):
        # An upright iPhone photo cropped to 4:3.
        self.assertEqual(cl.crop_box(3024, 4032, 4.0 / 3.0),
                         (0, 882, 3024, 882 + 2268))

    def test_landscape_to_portrait_keeps_the_middle(self):
        self.assertEqual(cl.crop_box(4032, 3024, 0.75),
                         (882, 0, 882 + 2268, 3024))

    def test_already_the_right_shape(self):
        self.assertEqual(cl.crop_box(3024, 4032, 0.75), (0, 0, 3024, 4032))
        self.assertEqual(cl.crop_box(4032, 3024, 4.0 / 3.0),
                         (0, 0, 4032, 3024))

    def test_square(self):
        self.assertEqual(cl.crop_box(100, 100, 4.0 / 3.0), (0, 12, 100, 87))
        self.assertEqual(cl.crop_box(100, 100, 0.75), (12, 0, 87, 100))


if __name__ == "__main__":
    unittest.main()
