# -*- coding: utf-8 -*-
"""Tests for callout_layout. Run from the repository root with:

    python -m unittest discover -s toolboxes/pictorial_maps/tests
"""

import io
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
        centres = cl.arrange_images(anchors, sizes)
        self.assert_good_layout(anchors, sizes, centres)
        # A lone photo gets its image directly above it.
        self.assertAlmostEqual(centres[0][0], 100.0, places=3)
        self.assertGreater(centres[0][1], 200.0)

    def test_photos_at_the_same_spot(self):
        anchors = [(0.0, 0.0)] * 6
        sizes = portrait_sizes(6)
        centres = cl.arrange_images(anchors, sizes)
        self.assert_good_layout(anchors, sizes, centres)

    def test_many_random_photos(self):
        rng = random.Random(7)
        for count in (2, 5, 25, 120):
            anchors = [(rng.uniform(0, 300), rng.uniform(0, 120))
                       for _ in range(count)]
            sizes = portrait_sizes(count, 1000, 60)
            for arrangement in cl.ARRANGEMENTS:
                centres = cl.arrange_images(anchors, sizes, arrangement)
                self.assert_good_layout(anchors, sizes, centres)
                self.assertEqual(self.count_crossings(anchors, centres), 0)

    def test_mixed_orientations(self):
        rng = random.Random(3)
        anchors = [(rng.uniform(0, 50), rng.uniform(0, 400))
                   for _ in range(12)]
        h = cl.page_points_to_map_units(90, 1000)
        sizes = [(h * 0.75, h) if i % 2 else (h * 1.33, h)
                 for i in range(12)]
        centres = cl.arrange_images(anchors, sizes)
        self.assert_good_layout(anchors, sizes, centres)

    def test_images_stay_near_their_photos(self):
        # Two well separated groups: each image should land on its own side.
        anchors = [(0.0, 0.0), (0.0, 10.0), (1000.0, 0.0), (1000.0, 10.0)]
        sizes = portrait_sizes(4, 500)
        centres = cl.arrange_images(anchors, sizes)
        self.assertLess(centres[0][0], 500)
        self.assertLess(centres[1][0], 500)
        self.assertGreater(centres[2][0], 500)
        self.assertGreater(centres[3][0], 500)


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
        out = os.path.join(self.tmp.name, "thumb.jpg")
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
        out = os.path.join(self.tmp.name, "thumb.jpg")
        width, height = cl.make_thumbnail(src, out, max_pixels=100)
        # 100 px of photo plus the mat and edge on both sides.
        self.assertLessEqual(max(width, height), 100 + 2 * (3 + 1))

    def test_data_url(self):
        out = os.path.join(self.tmp.name, "thumb.jpg")
        cl.make_thumbnail(self.sideways_photo_bytes(), out)
        url = cl.image_data_url(out)
        self.assertTrue(url.startswith("data:image/jpeg;base64,/9j/"))


if __name__ == "__main__":
    unittest.main()
