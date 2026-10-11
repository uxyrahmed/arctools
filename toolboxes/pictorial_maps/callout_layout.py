# -*- coding: utf-8 -*-
"""Layout and image helpers for the Photo Callouts tool.

Nothing in this module uses arcpy, so it can be tested outside ArcGIS Pro.
Coordinates are plain (x, y) tuples in the units of a projected coordinate
system, and image sizes are (width, height) tuples in the same units.
"""

import base64
import bisect
import io
import math

AROUND = "AROUND"
ROW_ABOVE = "ROW_ABOVE"
ARRANGEMENTS = (AROUND, ROW_ABOVE)

POINTS_PER_INCH = 72.0
METERS_PER_INCH = 0.0254

# Space left between neighbouring images, as a fraction of the image height.
GAP_FRACTION = 0.2

# Longest side of the thumbnails, in pixels. Big enough to print a photo about
# two inches tall at 300 dpi while keeping the project file small.
THUMBNAIL_PIXELS = 600

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif")


def page_points_to_map_units(page_points, scale, meters_per_unit=1.0):
    """Convert a size on the page (in points) to map units at a map scale."""
    meters = page_points / POINTS_PER_INCH * METERS_PER_INCH * scale
    return meters / meters_per_unit


def utm_wkid(longitude, latitude):
    """Return the WKID of the WGS 1984 UTM zone that contains a location."""
    zone = int(math.floor((longitude + 180.0) / 6.0)) + 1
    zone = min(max(zone, 1), 60)
    return (32600 if latitude >= 0 else 32700) + zone


def is_image_attachment(name, content_type):
    """True if an attachment looks like a photo we can read."""
    if content_type and content_type.lower().startswith("image/"):
        return True
    return bool(name) and name.lower().endswith(IMAGE_EXTENSIONS)


# ---------------------------------------------------------------------------
# Thumbnails
# ---------------------------------------------------------------------------


def make_thumbnail(source, out_path, max_pixels=THUMBNAIL_PIXELS):
    """Write a framed, upright JPEG thumbnail of a photo.

    `source` is a file path or the photo's bytes. Phone photos are often stored
    sideways with an EXIF tag saying how to rotate them; ArcGIS picture markers
    ignore that tag, so the rotation is applied to the pixels here.

    Returns the (width, height) of the thumbnail in pixels.
    """
    from PIL import Image, ImageOps

    if isinstance(source, (bytes, bytearray, memoryview)):
        source = io.BytesIO(bytes(source))

    with Image.open(source) as photo:
        photo = ImageOps.exif_transpose(photo).convert("RGB")
        resample = getattr(Image, "Resampling", Image).LANCZOS
        photo.thumbnail((max_pixels, max_pixels), resample)

        # A white mat with a thin dark edge keeps the photo readable on both
        # dark imagery and light sand.
        mat = max(3, round(max(photo.size) * 0.03))
        framed = ImageOps.expand(photo, border=mat, fill=(255, 255, 255))
        framed = ImageOps.expand(framed, border=1, fill=(60, 60, 60))
        framed.save(out_path, "JPEG", quality=85, optimize=True)
        return framed.size


def image_data_url(path):
    """Return a JPEG file as a data URL, the form ArcGIS Pro uses to embed
    pictures in symbols."""
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return "data:image/jpeg;base64," + encoded


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def arrange_images(anchors, sizes, arrangement=AROUND, gap=None):
    """Choose where each image goes.

    anchors     -- list of (x, y) photo locations
    sizes       -- list of (width, height) image sizes, same order as anchors
    arrangement -- AROUND: on a ring around all the photos, in the same order
                   as the photos so leader lines don't cross.
                   ROW_ABOVE: in one row above the highest photo, ordered
                   west to east.
    gap         -- space to keep between images. Defaults to a fraction of
                   the tallest image.

    Returns a list of (x, y) image centres in the same order as anchors.
    """
    if len(anchors) != len(sizes):
        raise ValueError("anchors and sizes must be the same length")
    if not anchors:
        return []
    if gap is None:
        gap = GAP_FRACTION * max(h for _, h in sizes)
    if arrangement == AROUND:
        centres = _ring_layout(anchors, sizes, gap)
    elif arrangement == ROW_ABOVE:
        centres = _row_above_layout(anchors, sizes, gap)
    else:
        raise ValueError("Unknown arrangement: {}".format(arrangement))
    return uncross(anchors, sizes, centres)


def spread(values, gaps):
    """Move sorted values apart as little as possible so that
    values[i + 1] - values[i] >= gaps[i].

    This is a least-squares fit: subtracting the running total of the gaps
    turns it into isotonic regression, solved with pool-adjacent-violators.
    """
    if len(gaps) != max(len(values) - 1, 0):
        raise ValueError("need one gap between each pair of values")
    offsets = [0.0]
    for g in gaps:
        offsets.append(offsets[-1] + g)
    shifted = [v - o for v, o in zip(values, offsets)]

    blocks = []  # [sum, count] of pooled runs
    for v in shifted:
        blocks.append([v, 1])
        while len(blocks) > 1 and (
            blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]
        ):
            total, count = blocks.pop()
            blocks[-1][0] += total
            blocks[-1][1] += count

    fitted = []
    for total, count in blocks:
        fitted.extend([total / count] * count)
    return [f + o for f, o in zip(fitted, offsets)]


def uncross(anchors, sizes, centres):
    """Swap images between photos until no two leader lines cross.

    Swapping the ends of two crossing lines always makes them shorter in
    total, so this finishes. Only images of the same size are swapped, so the
    set of image positions (and therefore overlaps) doesn't change.
    """
    centres = list(centres)
    count = len(anchors)
    for _ in range(count * count + 1):
        swapped = False
        for i in range(count):
            for j in range(i + 1, count):
                if (_same_size(sizes[i], sizes[j]) and segments_cross(
                        anchors[i], centres[i], anchors[j], centres[j])):
                    centres[i], centres[j] = centres[j], centres[i]
                    swapped = True
        if not swapped:
            break
    return centres


def _same_size(a, b):
    return all(abs(p - q) <= 1e-9 * max(abs(p), abs(q), 1.0)
               for p, q in zip(a, b))


def images_overlap(centres, sizes, gap=0.0):
    """True if any two images (plus half the gap around each) overlap."""
    for i in range(len(centres)):
        (xi, yi), (wi, hi) = centres[i], sizes[i]
        for j in range(i + 1, len(centres)):
            (xj, yj), (wj, hj) = centres[j], sizes[j]
            if (abs(xi - xj) < (wi + wj) / 2.0 + gap and
                    abs(yi - yj) < (hi + hj) / 2.0 + gap):
                return True
    return False


def _row_above_layout(anchors, sizes, gap):
    tallest = max(h for _, h in sizes)
    row_y = max(y for _, y in anchors) + tallest + gap

    order = sorted(range(len(anchors)), key=lambda i: anchors[i][0])
    xs = [anchors[i][0] for i in order]
    gaps = [
        (sizes[a][0] + sizes[b][0]) / 2.0 + gap
        for a, b in zip(order, order[1:])
    ]
    placed = spread(xs, gaps)

    centres = [None] * len(anchors)
    for i, x in zip(order, placed):
        centres[i] = (x, row_y)
    return centres


class _Ellipse:
    """An axis-aligned ellipse that can be walked by distance along its edge."""

    SAMPLES = 2048

    def __init__(self, cx, cy, a, b):
        self.cx, self.cy, self.a, self.b = cx, cy, a, b
        self.lengths = [0.0]
        x0, y0 = self._at(0.0)
        for k in range(1, self.SAMPLES + 1):
            x1, y1 = self._at(2.0 * math.pi * k / self.SAMPLES)
            self.lengths.append(self.lengths[-1] + math.hypot(x1 - x0, y1 - y0))
            x0, y0 = x1, y1
        self.perimeter = self.lengths[-1]

    def _at(self, t):
        return (self.cx + self.a * math.cos(t), self.cy + self.b * math.sin(t))

    def distance_towards(self, x, y):
        """Distance along the edge to where a ray from the centre through
        (x, y) meets the ellipse."""
        dx, dy = x - self.cx, y - self.cy
        if dx == 0 and dy == 0:
            dy = 1.0  # a photo at the very centre points straight up
        t = math.atan2(self.a * dy, self.b * dx) % (2.0 * math.pi)
        k = t / (2.0 * math.pi) * self.SAMPLES
        lower = min(int(k), self.SAMPLES - 1)
        frac = k - lower
        return self.lengths[lower] + frac * (
            self.lengths[lower + 1] - self.lengths[lower])

    def point_at(self, distance):
        """The point at a distance along the edge."""
        distance %= self.perimeter
        k = bisect.bisect_right(self.lengths, distance) - 1
        k = min(max(k, 0), self.SAMPLES - 1)
        step = self.lengths[k + 1] - self.lengths[k]
        frac = (distance - self.lengths[k]) / step if step else 0.0
        return self._at(2.0 * math.pi * (k + frac) / self.SAMPLES)


def _ring_layout(anchors, sizes, gap):
    xs = [x for x, _ in anchors]
    ys = [y for _, y in anchors]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0

    # The ellipse through the corners of the photos' bounding box, pushed out
    # far enough that no image covers a photo point.
    half_diagonal = max(math.hypot(w, h) for w, h in sizes) / 2.0
    margin = half_diagonal + gap
    a = (max(xs) - min(xs)) / 2.0 * math.sqrt(2.0) + margin
    b = (max(ys) - min(ys)) / 2.0 * math.sqrt(2.0) + margin

    spacing = max(max(w, h) for w, h in sizes) + gap
    count = len(anchors)
    for _ in range(40):
        ellipse = _Ellipse(cx, cy, a, b)
        if ellipse.perimeter < count * spacing:
            # Not enough room on the ring: make it bigger.
            grow = (count * spacing - ellipse.perimeter) / (2.0 * math.pi)
            a += grow
            b += grow
            continue

        centres = _place_on_ring(ellipse, anchors, spacing)
        if not images_overlap(centres, sizes, gap / 2.0):
            return centres
        # Neighbours can still touch where the ring curves tightly (the ends
        # of a long, thin group of photos). Space them out more and retry.
        spacing *= 1.15
    return centres


def _place_on_ring(ellipse, anchors, spacing):
    count = len(anchors)
    perimeter = ellipse.perimeter
    natural = [ellipse.distance_towards(x, y) for x, y in anchors]
    order = sorted(range(count), key=lambda i: natural[i])
    ordered = [natural[i] for i in order]

    if count == 1:
        placed = ordered
    else:
        # Open the ring at its widest empty stretch, spread the images along
        # the resulting line, then wrap back onto the ring.
        gaps = [ordered[k + 1] - ordered[k] for k in range(count - 1)]
        gaps.append(ordered[0] + perimeter - ordered[-1])
        start = (gaps.index(max(gaps)) + 1) % count
        order = order[start:] + order[:start]
        unrolled = ordered[start:] + [d + perimeter for d in ordered[:start]]

        placed = spread(unrolled, [spacing] * (count - 1))
        if placed[-1] - placed[0] > perimeter - spacing:
            # Too crowded to keep each image near its photo: space them evenly,
            # turned to sit as close as possible to where they want to be.
            step = perimeter / count
            turn = sum(u - k * step for k, u in enumerate(unrolled)) / count
            placed = [turn + k * step for k in range(count)]

    centres = [None] * count
    for i, distance in zip(order, placed):
        centres[i] = ellipse.point_at(distance)
    return centres


def segments_cross(p1, p2, q1, q2):
    """True if segment p1-p2 properly crosses segment q1-q2."""

    def side(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2 = side(q1, q2, p1), side(q1, q2, p2)
    d3, d4 = side(p1, p2, q1), side(p1, p2, q2)
    return d1 * d2 < 0 and d3 * d4 < 0
