# Survey Location Map toolbox

Tools that turn a survey KMZ into a Survey Location Map: they import the survey
points, draw the transect lines, connect the data to the master layout and
tidy the layout so it shows only the surveys in the KMZ. You add the drone
image and fill in the title block.

| Tool | What it does |
| ---- | ------------ |
| **Make Survey Map (All in One)** | Runs Steps 1 to 4 in order, from just the KMZ and the layout. |
| **Step 1 Import Survey KMZ** | Converts the KMZ and splits its features into one feature class per survey by name prefix. Points keep Name, X and Y; lines keep Name. Everything else in the KMZ is left out. |
| **Step 2 Draw Transect Lines** | Draws a 50 m line from each transect point, in the compass direction in its name. |
| **Step 3 Connect Data to Layout** | Points each survey layer in the master layout at its new data, links each survey's table to its layer and labels the points. |
| **Step 4 Restyle Layout** | Hides the surveys that aren't in the KMZ, sizes each table to its rows and stacks the tables in the Tables Panel. |

Each step also works on its own, for example to run Step 4 again after moving
something by hand.

## Workflow

1. In a new project, import the master layout: **Insert** > **Import Layout**,
   then browse to the master `.pagx` (see [Master layout](#master-layout)).
2. Open the layout's survey map and add the drone image (TIF).
3. Run **Make Survey Map (All in One)** with the survey KMZ. The layout is
   picked for you when it's the active view, the only layout, or the only one
   with "survey" in its name.
4. Fill in the title block: Project, Client, Map Title and Revision.
5. Check the map and export it.

## Surveys

Features are sorted by the letters their names start with, in any case:
`SW201` is sea water sampling, `P1` is a beach profile and `C201 start` is a
current point.

| Survey | KMZ prefix | Feature class | Layer in the master layout | Table | Heading |
| ------ | ---------- | ------------- | -------------------------- | ----- | ------- |
| Sea water sampling | SW | `SW_Points` | Sea Water Sampling Points | SW Table | SW Heading |
| Visual snorkelling survey | VSS | `VSS_Points` | Visual Snorkelling Survey Points | VSS Table | VSS Heading |
| Visual snorkelling survey lines | VSS (lines) | `VSS_Lines` | Visual Snorkelling Survey Lines | | |
| Marine transects | T | `T_Points` | Marine Transects | T Table | T Heading |
| Transect lines | drawn by Step 2 | `T_Lines` | Transect Line | | |
| Beach profiles | P or BP | `BP_Points` | Beach Profiles | BP Table | BP Heading |
| Ground water sampling | GW | `GW_Points` | Ground Water Sampling Points | GW Table | GW Heading |
| Currents | C | `C_Points` | Currents Survey Points | C Table | C Heading |
| Noise survey | N | `N_Points` | Noise Survey Points | N Table | N Heading |

- Of the lines in the KMZ, only VSS lines are kept. Other lines and all
  polygons (building outlines, bathymetry and so on) are left out, and Step 1
  says how many.
- Points whose prefix isn't in the table are saved as `<PREFIX>_Points`, with
  a warning, but don't go on the map. Points whose names don't start with a
  letter are left out, with a warning.
- Names are used as they are in the KMZ.

### Transect lines

Transect names hold the ID, the direction and usually the depth, for example
`T201 S 2m`. Step 2 draws a line from each point in that direction: south for
`T201 S 2m`.

- All 16 compass points work: N, NNE, NE, ENE, E, ESE, SE, SSE, S, SSW, SW,
  WSW, W, WNW, NW and NNW, in any case. So do words (`South`, `North East`,
  `north-west`) and a direction run into the depth (`S2m`, `NE3.5m`).
- The first word is the transect's ID, so it's never read as a direction.
- A point with no direction in its name gets no line, and Step 2 lists those
  points.
- Lines are worked out in metres in UTM (or the coordinate system you choose),
  so each is exactly the length you set.

### X and Y

X and Y default to WGS 1984 UTM Zone 43N, or 43S when the points are south of
the equator. Choose another coordinate system in **Coordinate System for X and
Y**. Values are rounded to 3 decimal places (6 for degrees). The features
themselves stay in WGS 1984, like the KMZ.

## Parameters

### Make Survey Map (All in One)

- **Survey KMZ:** the `.kmz` or `.kml` with the survey points.
- **Layout:** the master layout in this project.
- **Output Folder:** where the survey geodatabase goes. Defaults to the
  project folder.
- **Geodatabase Name:** filled in from the KMZ's file name. Running again with
  the same name replaces that geodatabase's survey data.
- **Coordinate System for X and Y:** optional; see [X and Y](#x-and-y).
- **Transect Line Length (metres):** 50 unless you change it.
- **Table Spacing:** *Stack from top* (default) puts the tables at the top of
  the Tables Panel with even gaps between them, like the Funadhoo example.
  *Spread evenly* spaces them down the whole panel.

### Step 1 Import Survey KMZ

- **Survey KMZ**, **Output Folder**, **Geodatabase Name** and **Coordinate
  System for X and Y**, as above.
- Writes the feature classes in [Surveys](#surveys), only for the surveys the
  KMZ has. Feature classes from an earlier run are emptied and filled again
  rather than replaced, so running again works while the layout shows them.
  Ones the new KMZ doesn't have are emptied, including `T_Lines`, which
  Step 2 draws again.

### Step 2 Draw Transect Lines

- **Transect Points:** `T_Points` from Step 1, or any point layer with a Name
  field. With a selection, only the selected points get lines.
- **Output Transect Lines:** defaults to `T_Lines` next to the points. It's
  replaced on every run.
- **Transect Line Length (metres):** 50 unless you change it.
- **Coordinate System to Draw In:** optional, a projected coordinate system
  to work the lines out in. Leave it blank for UTM 43N or 43S.

### Step 3 Connect Data to Layout

- **Layout** and **Survey Geodatabase** (the `.gdb` from Step 1).
- Each survey layer with data is pointed at its feature class, its definition
  query is cleared and it's turned on. Point layers are labelled with Name in
  Tahoma Regular 12 pt, white, with a 2 pt black halo. Line layers get no
  labels. Layers of surveys with no data are turned off.
- Each survey's table is linked to its layer and set to show Name, X and Y.

### Step 4 Restyle Layout

- **Layout**, **Survey Geodatabase** and **Table Spacing**.
- The tables, headings and legend entries of surveys with no data are hidden.
  The legend shows only the survey layers with data; anything else in it, such
  as the drone image, is hidden.
- Each visible table is sized to fit its rows at its full text size, then the
  headings and tables are stacked inside the Tables Panel, each heading just
  above its table and centred across the panel. They keep the order they have
  in the layout, top to bottom. The panel itself isn't moved or resized.
- If the tables don't fit, they're all squeezed by the same amount and ArcGIS
  Pro shrinks their text to fit. The tool warns when that happens; make the
  panel taller or the table text smaller in the master layout.

## When something goes wrong

- A problem with one survey, layer, table or heading is a warning: the tool
  skips that piece, says what it skipped and why, and carries on.
- Data that's locked, for example open in another ArcGIS Pro window or being
  synced by OneDrive, is tried again a couple of times before the tool gives
  up on it.
- **Make Survey Map (All in One)** stops only when it can't go on: Step 1
  couldn't read the KMZ or write any survey data, or Step 3 couldn't find the
  survey map or connect any layer. If Step 2 fails, it carries on without
  transect lines. If Step 4 fails, the data is still on the map and you can
  run Step 4 on its own.
- Only what this run imported goes on the map. A survey that couldn't be
  written is left off rather than shown with old data.
- An unexpected error is one line, followed by **Details for
  troubleshooting**. Send those details when reporting it.
- The KMZ is converted in Windows' temporary folder, not the project folder,
  so OneDrive doesn't hold it open.

## Master layout

The tools find everything in the layout **by name**, so the names must match
(capitals and extra spaces don't matter). Anything else, such as the title
block, mini map, north arrow, scale bar and logo, is left alone.

1. **Survey layers:** all 9 layers in the [Surveys](#surveys) table, in the
   map shown in the main map frame, each styled the way it should look. The
   layer name is also the legend text. Labels don't need setting up; Step 3
   sets them on every run. Broken data links are fine, since Step 3 repoints
   every layer.
2. **Tables:** one table frame per point survey, named like `SW Table` and
   showing Name, X and Y in that order. The text size you give the tables is
   the size they're drawn at.
3. **Headings:** one text element per point survey, named like `SW Heading`.
   The wording is up to you.
4. **Tables Panel:** a rectangle named `Tables Panel` over the area the tables
   fill. It can be visible, for example as the column's border.
5. **Legend:** linked to the main map frame.

To rename an element, select it in the layout's Contents pane and press F2.

## Adding a survey

1. Add a line to `SURVEYS` in `surveymap/surveys.py`: its code (used in the
   table and heading names), layer name, `POINT` or `POLYLINE`, KMZ prefixes
   and feature class name.
2. Add the layer, and for points the table and heading, to the master layout.
3. Run the tests (below), then refresh the toolbox in ArcGIS Pro.

## Notes

- Table heights are worked out from each table's text size and gaps, since
  ArcGIS Pro doesn't report how tall a table needs to be. If tables come out a
  little too tall or short, `LINE_HEIGHT` and the padding in
  `surveymap/stacking.py` are the numbers to adjust.
- The survey map is the one shown in the map frame with the most survey
  layers, so other maps in the layout (location maps, mini map) don't matter.
- ArcGIS Pro keeps Python modules loaded, so the toolbox drops any
  `surveymap` already in memory and loads the copy next to it whenever
  ArcGIS Pro loads it. After editing the code or unzipping a new copy,
  right-click the toolbox in the Catalog pane and choose **Refresh**.
- The code is written for ArcGIS Pro 3.0 and later (Python 3.9 and up).

## Tests

The survey names, direction reading, table stacking and error message code
is in `surveymap/surveys.py`, `directions.py`, `stacking.py` and
`messages.py`, which don't need ArcGIS. Their tests run with any Python 3:

```
python -m unittest discover -s toolboxes/survey_location_map/tests
```
