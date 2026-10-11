# arctools

A collection of toolboxes and tools for ArcGIS Pro.

## Repository layout

```
arctools/
├── toolboxes/        # Toolboxes you can add to an ArcGIS Pro project
│   └── _template/    # Starter Python toolbox (.pyt) to copy for new tools
├── scripts/          # Standalone arcpy scripts that run outside a toolbox
└── data/
    └── images/       # Photos used as input data for the tools
```

Each toolbox lives in its own folder under `toolboxes/`, along with any helper
modules, sample data or notes it needs.

## Requirements

- ArcGIS Pro 3.x
- The Python environment that ships with ArcGIS Pro (`arcgispro-py3`), which
  includes `arcpy`

## Using a toolbox in ArcGIS Pro

1. Clone or download this repository.
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
| _None yet_ | |
