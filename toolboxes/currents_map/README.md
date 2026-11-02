# Currents Map

Turns the field device's currents CSV into a currents map: an arrow for each
current, from where it started to where it ended, labelled with its speed and
direction, like `0.21 m/s S`.

The same arrows are in the Survey Location Map toolbox (Step 3). This toolbox
is for making a map of just the currents, and doesn't need a survey KMZ.

## Tools

| Tool | What it does |
| ---- | ------------ |
| **Make Currents Map (All in One)** | Runs Steps 1 and 2 in order, from just the CSV and the map. |
| **Step 1 Draw Current Arrows** | Works out each current's speed and direction from the CSV and saves the arrows (`C_Arrows`) and the start and end points (`C_Points`) in a file geodatabase. |
| **Step 2 Add Currents to Map** | Shows the arrows on a map as a layer called **Currents**, labelled with speed and direction, and zooms to them. |

Each step works on its own: Step 2 reads what it needs from the geodatabase,
so you can run it again on another map, or after restyling, without redoing
Step 1.

## Workflow

1. Unzip the toolbox and add `CurrentsMap.pyt` to your project (Catalog pane >
   Toolboxes > Add Toolbox).
2. Open the map the currents should go on, with the drone image or basemap
   you want under them.
3. Run **Make Currents Map (All in One)** with the currents CSV. The map open
   now is picked for you, and the geodatabase is named after the CSV.
4. Check the arrows and labels, then lay out and export the map as usual.

## The currents CSV

One row per point, as the field device writes it:

```
Name,Latitude,Longitude,UTM,Date Record
C1 start,5.668124596,73.03368956,282219.358E 626887.752N 43N,15/10/2026 14:13
C1 end,5.667565087,73.03367984,282218.071E 626825.871N 43N,15/10/2026 14:18
```

- Each current has a start and an end point, named like `C1 start` and
  `C1 end` (`C1_END` and `C1end` work too). Two points with the same name and
  no start or end in it are taken in the order they were recorded.
- Points whose names don't start with C (for example other survey points in
  the same CSV) are left out. If no name starts with C, every point is used.
- The speed is the distance from start to end over the time between them, in
  metres per second. The direction is the way the current went, from start
  to end, as the nearest of the 16 compass points. With the CSV above, C1
  moved 61.9 m south in 5 minutes: `0.21 m/s S`.
- The position comes from Latitude and Longitude, or the UTM column if those
  are missing. The time comes from a column with "date" or "time" in its
  name, or a Date and a Time column together. Dates are read day first
  (15/10/2026).
- A point that can't be read, or a current with no start, no end or an end
  that isn't after its start, is skipped with a warning saying why.

## Parameters

### Make Currents Map (All in One)

Takes every parameter of Steps 1 and 2.

### Step 1 Draw Current Arrows

- **Currents CSV:** the CSV from the field device.
- **Output Folder:** where the geodatabase goes. Defaults to the project's
  home folder.
- **Geodatabase Name:** filled in from the CSV name. If a geodatabase with
  this name is already in the folder (for example the survey geodatabase from
  the Survey Location Map), the currents are written into it.
- **Coordinate System to Measure In:** optional. Distances, and X and Y of the
  start and end points, are worked out in this coordinate system. Left empty,
  WGS 1984 UTM Zone 43N is used (43S south of the equator).

It writes, in WGS 1984:

- `C_Arrows`: one line per current, start to end, with `Label` (`0.21 m/s S`),
  `Speed_ms`, `Bearing`, `Direction`, `Distance_m`, `Minutes`, `Start_Time`
  and `End_Time`.
- `C_Points`: each current's start and end point, with `Current`, `Point`
  (Start or End), `Time`, and `X` and `Y` to 2 decimals.

### Step 2 Add Currents to Map

- **Currents Geodatabase:** the geodatabase Step 1 wrote to.
- **Map:** the map to show the currents on. Defaults to the map open now.
- **Show Start and End Points:** off by default. On, the start and end points
  are shown too, as a layer called **Currents Survey Points** labelled with
  their names.
- **Zoom to Currents:** on by default. Zooms the map to the currents, with
  some space around them, when it's the map open now.

The first time, a **Currents** layer is added, drawn as white arrows with a
black edge and labelled in white Tahoma 12 with a black halo, like the Survey
Location Map. If the map already has a layer called **Currents** (or
**Currents Survey Points**), it's pointed at the new data and keeps its
style, so restyle it once and it stays that way.

## Files

`CurrentsMap.pyt` holds the tools. The `currentsmap` folder holds the code:
`currents.py` reads the CSV and works out speed and direction,
`arrows.py` writes the geodatabase, and `maps.py` puts it on the map.
`currents.py`, `directions.py`, `common.py` and `messages.py` don't need
ArcGIS, so the tests run on any Python 3:

```
python -m unittest discover -s toolboxes/currents_map/tests
```
