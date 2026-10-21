# -*- coding: utf-8 -*-
"""Turn hand-drawn shoreline lines into zones the model can learn from.

No arcpy here, only numpy and scipy, so the tests can run anywhere. The
toolbox draws the lines onto a grid (see gis.py) and hands the grids to
make_labels.

The zones, from the sea inwards:
  1 Water        seaward of the low tide line
  2 Intertidal   between the low tide line and the high tide line
  3 Dry beach    between the high tide line and the vegetation line
  4 Vegetation   inside the vegetation line (trees, and on resort islands
                 the developed land too, since that is what the team traces)
  0 No label     the model is not taught anything here
"""

import numpy as np
from scipy import ndimage

NO_LABEL = 0
WATER = 1
INTERTIDAL = 2
DRY_BEACH = 3
VEGETATION = 4

CLASS_NAMES = {
    WATER: "Water",
    INTERTIDAL: "Intertidal",
    DRY_BEACH: "Dry beach",
    VEGETATION: "Vegetation",
}


def make_labels(low_tide, vegetation, high_tide, cell_size,
                high_tide_reach=50.0, sea_band=60.0, land_band=80.0):
    """Zone grid for one survey.

    low_tide:   bool grid, True inside the low tide line polygon(s).
    vegetation: bool grid, True inside the vegetation line polygon(s).
    high_tide:  bool grid, True on the high tide line.
    cell_size:  metres per cell.

    The high tide line comes in pieces, with gaps where there is a seawall or
    jetty, so it can't be closed into a polygon. Instead, each beach cell is
    compared with the nearest point on the high tide line: a cell closer to
    the water than that point is intertidal, otherwise it is dry beach. Beach
    cells more than high_tide_reach metres from any high tide line get no
    label, because nothing says where the line would be there.

    Only a band around the coast is labelled: sea_band metres out to sea and
    land_band metres inland from the low tide line. Deep water and the island
    interior teach the model little and would swamp the beach.
    """
    low_tide = np.asarray(low_tide, dtype=bool)
    vegetation = np.asarray(vegetation, dtype=bool) & low_tide
    high_tide = np.asarray(high_tide, dtype=bool) & low_tide
    if not (low_tide.shape == vegetation.shape == high_tide.shape):
        raise ValueError("The three grids must be the same size.")

    labels = np.zeros(low_tide.shape, dtype=np.uint8)
    if not low_tide.any():
        return labels

    labels[~low_tide] = WATER
    labels[vegetation] = VEGETATION

    beach = low_tide & ~vegetation
    if high_tide.any() and beach.any():
        # Distance from every land cell to the nearest water cell.
        to_water = ndimage.distance_transform_edt(low_tide, sampling=cell_size)
        # Distance to, and position of, the nearest high tide line cell.
        to_line, (rows, cols) = ndimage.distance_transform_edt(
            ~high_tide, sampling=cell_size, return_indices=True)
        line_to_water = to_water[rows, cols]

        near = beach & (to_line <= high_tide_reach)
        seaward = to_water < line_to_water
        labels[near & seaward] = INTERTIDAL
        labels[near & ~seaward] = DRY_BEACH

    # Keep only the coastal band.
    out_to_sea = ndimage.distance_transform_edt(~low_tide, sampling=cell_size)
    inland = ndimage.distance_transform_edt(low_tide, sampling=cell_size)
    band = np.where(low_tide, inland <= land_band, out_to_sea <= sea_band)
    labels[~band] = NO_LABEL
    return labels


def class_counts(labels):
    """How many cells of each zone there are, as {name: count}, so the tool
    can say what it labelled."""
    counts = np.bincount(np.asarray(labels).ravel(), minlength=VEGETATION + 1)
    result = {CLASS_NAMES[value]: int(counts[value]) for value in CLASS_NAMES}
    result["No label"] = int(counts[NO_LABEL])
    return result


def train_mask(labels):
    """Where training tiles may come from: labelled cells only."""
    return np.asarray(labels) != NO_LABEL
