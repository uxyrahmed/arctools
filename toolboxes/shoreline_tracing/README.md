# Shoreline Tracing

Teaches a deep learning model to draw CDE's shoreline lines (low tide, high
tide and vegetation) from a drone orthomosaic, using shorelines the team has
already drawn by hand as the examples. The model drafts the lines and a person
checks and fixes them.

## What you need

- ArcGIS Pro 3.x with the **Image Analyst** extension.
- Esri's **Deep Learning Libraries** installer for your exact Pro version.
- An NVIDIA graphics card. Training works without one, but is much slower.
  Check Pro can see the card by pasting this into Pro's Python window:

  ```python
  import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0)); print(torch.ones(1).cuda() + 1)
  ```

  It should print `True` and the card's name. RTX 50 series cards need a
  recent Pro and libraries.

## The zones

The tools turn each survey's lines into four zones, from the sea inwards:

| Value | Zone        | Where |
| ----- | ----------- | ----- |
| 1     | Water       | seaward of the low tide line |
| 2     | Intertidal  | between the low tide and high tide lines |
| 3     | Dry beach   | between the high tide and vegetation lines |
| 4     | Vegetation  | inside the vegetation line (on resorts, the developed land too) |

The model learns to colour every pixel with one of these, and the edges
between the zones become the lines again.

The high tide line is drawn in pieces, with gaps at seawalls and jetties, so
it can't be closed into a polygon. Each beach pixel is compared with the
nearest point on the high tide line instead: closer to the water than that
point means intertidal, otherwise dry beach. Beach more than 50 m from any
high tide piece gets no label, so the model isn't taught a guess.

Only a band around the coast is used: 60 m out to sea and 80 m inland from
the low tide line.

## The lines must match the image

Each survey's lines must have been drawn on that same drone image. If the
image was flown on another day or tide, the low tide line ends up in open
water or on dry sand, and the model learns the wrong thing. Check by adding
the image and the three lines to a map before preparing the training data.

## Tools

### 1. Prepare Training Data

Run once with all the past surveys you want to train on.

- **Surveys**: one row per survey with the drone image, low tide line
  (polygons), high tide line (lines) and vegetation line (polygons).
- **Output training folder**: gets one subfolder of tiles per survey, plus
  `zones.gdb` with each survey's zones as polygons. Add those to a map to
  check the zones look right.
- Advanced: **Tile cell size** (default 0.15 m; images are resampled to it),
  **Tile size** (256 pixels, so each tile covers about 38 m), **High tide
  line reach** (50 m).

Leave one survey out if you want to measure accuracy afterwards (see 4).

### 2. Train Shoreline Model

- **Training folder**: the output folder of tool 1.
- **Output model folder**: gets the trained model (`.dlpk`).
- **Maximum epochs** (50) and **Batch size** (8). Training stops early when
  the model stops improving. If you run out of graphics memory, lower the
  batch size.
- Advanced: **Backbone** (RESNET34, or RESNET50 for a bigger model) and
  **Model arguments** passed straight to Train Deep Learning Model.

### 3. Trace Shoreline

- **Drone image**: a new orthomosaic.
- **Model**: the `.dlpk` from tool 2.
- **Output folder**: gets `Low Tide Line.shp`, `High Tide Line.shp` and
  `Vegetation Line.shp`, named like the hand-drawn ones, plus `zones.tif`,
  which shows the model's zones.
- **Survey date** (optional) is written into a SurveyDate field.
- Advanced: the cell size (read from the model folder by default), the
  smallest island kept (50 m²), the largest hole filled (200 m²), smoothing
  (2 m), the gap where vegetation meets the water (1 m) and the shortest high
  tide piece kept (5 m).

### 4. Check Accuracy

Trace a survey the model was not trained on, then compare:

- **Traced lines folder**: the output folder of tool 3.
- **Hand-drawn lines folder**: the folder with that survey's hand-drawn
  shapefiles.

For each line it reports how far the hand-drawn line is from the traced one,
from a point every metre: the typical gap, the 90% figure and the share
within 0.5, 1 and 2 m. **Output CSV** saves the same numbers.

## Running the tests

The zone and scoring logic has no arcpy, so it can be tested anywhere:

```
python -m unittest discover -s toolboxes/shoreline_tracing/tests
```
