# arctools

A collection of toolboxes and tools for ArcGIS Pro.

## Repository layout

```
arctools/
├── toolboxes/        # Toolboxes you can add to an ArcGIS Pro project
│   ├── _template/    # Starter Python toolbox (.pyt) to copy for new tools
│   └── survey_location_map/  # Survey Location Map toolbox (survey KMZ to map layout)
├── scripts/          # Standalone arcpy scripts, and the script that zips a toolbox for a release
└── data/
    └── images/       # Photos used as input data for the tools
```

Each toolbox lives in its own folder under `toolboxes/`, along with any helper
modules, sample data or notes it needs.

## Requirements

- ArcGIS Pro 3.x
- The Python environment that ships with ArcGIS Pro (`arcgispro-py3`), which
  includes `arcpy`

## Downloading a toolbox

Each toolbox has its own release with a zip of just that toolbox. Open
[Releases](https://github.com/uxyrahmed/arctools/releases), find the newest
release for the toolbox you want (for example `survey-location-map-v1.0`) and
download the zip under **Assets**. Unzip it anywhere and add the `.pyt` inside
(see below).

Releases are made automatically: every time a change to a toolbox lands on
`main`, that toolbox gets a new release (v1.0, v1.1, v1.2, ...) listing what
changed. Toolboxes that didn't change keep their last release. To re-release
a toolbox by hand, run **Release toolboxes** from the Actions tab. To jump to a
new major version, put it in a `VERSION` file in the toolbox folder (for
example `2.0`).

## Using a toolbox in ArcGIS Pro

1. Download the toolbox's zip from [Releases](#downloading-a-toolbox), or clone
   or download this repository.
2. In ArcGIS Pro, open the **Catalog** pane.
3. Right-click **Toolboxes** > **Add Toolbox**, then browse to the `.pyt` or
   `.atbx` file under `toolboxes/`.
4. Expand the toolbox and double-click a tool to open it in the
   **Geoprocessing** pane.

To make the toolboxes available in every project, add a folder connection to
your clone of this repository instead.

## Adding a new toolbox

1. Copy `toolboxes/_template/` to `toolboxes/<your_toolbox_name>/`.
2. Rename `Template.pyt` and update the toolbox `label` and `alias`.
3. Rename the `TemplateTool` class, define its parameters in
   `getParameterInfo`, and put the tool logic in `execute`.
4. Add the toolbox to a project (see above) to test it. After editing a `.pyt`,
   right-click it in the Catalog pane and choose **Refresh** to reload it.
5. Add a short entry for it in the table below.

## Toolboxes

| Toolbox | Description |
| ------- | ----------- |
| [Survey Location Map](toolboxes/survey_location_map/) | Turns a survey KMZ into a Survey Location Map. **Import Survey KMZ** splits the survey points into one feature class per survey with Name, X and Y; **Draw Transect Lines** draws a 50 m line from each transect point in the direction in its name; **Connect Data to Layout** and **Restyle Layout** point the master layout at the new data, hide the surveys that aren't there and stack the tables to fit. **Make Survey Map** runs all four. See the [toolbox README](toolboxes/survey_location_map/README.md) for the workflow and the names the master layout needs. |
