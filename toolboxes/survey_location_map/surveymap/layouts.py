# -*- coding: utf-8 -*-
"""Steps 3 and 4: connect the survey data to the master layout, then tidy the
layout so it only shows the surveys that are present.

The layout's layers, tables and headings are found by name; see README.md for
the names the master layout needs.
"""

import copy
import os

import arcpy

from . import gis, stacking, surveys

TABLE_FIELDS = ("Name", "X", "Y")


# --- Finding things ---------------------------------------------------------


def current_project():
    try:
        return arcpy.mp.ArcGISProject("CURRENT")
    except Exception:
        raise surveys.SurveyMapError(
            "Run this tool from ArcGIS Pro, with the project that holds the "
            "layout open."
        )


def layout_choices():
    """(layout names, default name) for the open project, or ([], None) when
    no project is open."""
    try:
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        names = [layout.name for layout in aprx.listLayouts()]
    except Exception:
        return [], None
    default = None
    try:
        view = aprx.activeView
        if view is not None and type(view).__name__ == "Layout":
            default = view.name
    except Exception:
        pass
    if default is None:
        survey_layouts = [name for name in names if "survey" in name.casefold()]
        if len(survey_layouts) == 1:
            default = survey_layouts[0]
        elif len(names) == 1:
            default = names[0]
    return names, default


def get_layout(aprx, name):
    for layout in aprx.listLayouts():
        if layout.name == name:
            return layout
    raise surveys.SurveyMapError(f"There's no layout called '{name}' in this project.")


def check_geodatabase(gdb):
    path = str(gdb or "")
    if not path.lower().endswith(".gdb") or not arcpy.Exists(path):
        raise surveys.SurveyMapError(
            f"Choose the file geodatabase that Step 1 made (a .gdb folder), not: {path}"
        )
    return path


def survey_layers(map_):
    """Survey code -> layer, for the survey layers in a map, matched by name."""
    wanted = {surveys.normalise(survey.layer_name): survey for survey in surveys.SURVEYS}
    found = {}
    for layer in map_.listLayers():
        survey = wanted.get(surveys.normalise(layer.name))
        if survey is None or survey.code in found:
            continue
        if layer.isFeatureLayer or _cim_type(layer.getDefinition("V3")) == "CIMFeatureLayer":
            found[survey.code] = layer
    return found


def find_survey_map_frame(layout):
    """The map frame showing the map with the most survey layers in it."""
    best_key = best = None
    for frame in layout.listElements("MAPFRAME_ELEMENT"):
        map_ = frame.map
        if map_ is None:
            continue
        found = len(survey_layers(map_))
        if not found:
            continue
        key = (found, bool(frame.visible), frame.elementWidth * frame.elementHeight)
        if best_key is None or key > best_key:
            best_key, best = key, frame
    if best is None:
        raise surveys.SurveyMapError(
            f"None of the map frames in layout '{layout.name}' shows a map with "
            "survey layers in it. The layers need the names in the README, such "
            "as 'Sea Water Sampling Points'."
        )
    return best


def present_surveys(gdb):
    """Survey code -> feature count, for the surveys with data in gdb."""
    counts = {}
    for survey in surveys.SURVEYS:
        path = os.path.join(gdb, survey.feature_class)
        if arcpy.Exists(path):
            count = gis.count(path)
            if count:
                counts[survey.code] = count
    return counts


# --- Step 3: connect the data -----------------------------------------------


def connect_data(layout_name, gdb):
    """Point each survey layer in the layout's map at its feature class in gdb,
    link each survey's table to its layer and set the point labels. Surveys
    with no data are turned off."""
    gdb = check_geodatabase(gdb)
    layout = get_layout(current_project(), layout_name)
    frame = find_survey_map_frame(layout)
    layers = survey_layers(frame.map)
    present = present_surveys(gdb)
    if not present:
        raise surveys.SurveyMapError(
            f"There's no survey data in {gdb}. Run Step 1 Import Survey KMZ first."
        )
    arcpy.AddMessage(f"Survey map: '{frame.map.name}', shown in map frame '{frame.name}'.")

    connected, turned_off = [], []
    for survey in surveys.SURVEYS:
        layer = layers.get(survey.code)
        if layer is None:
            continue
        if survey.code in present:
            _set_data_source(layer, gdb, survey.feature_class)
            _set_labels(layer, survey)
            layer.visible = True
            connected.append(f"{survey.layer_name} ({present[survey.code]})")
        else:
            layer.visible = False
            turned_off.append(survey.layer_name)

    definition = layout.getDefinition("V3")
    tables = _elements_by_name(definition, "CIMTableFrame")
    missing_tables = []
    for survey in surveys.point_surveys():
        table = tables.get(surveys.normalise(survey.table_name))
        layer = layers.get(survey.code)
        if table is None:
            missing_tables.append(survey.table_name)
        elif layer is not None:
            table.mapFrame = frame.name
            table.mapMemberURI = layer.getDefinition("V3").uRI
            _set_table_fields(table)
    layout.setDefinition(definition)

    if connected:
        arcpy.AddMessage("Connected: " + "; ".join(connected))
    if turned_off:
        arcpy.AddMessage("Turned off, not in this KMZ: " + "; ".join(turned_off))
    lost = [s.layer_name for s in surveys.SURVEYS if s.code in present and s.code not in layers]
    if lost:
        arcpy.AddWarning(
            "This KMZ has data for layers the survey map doesn't have, so that "
            "data isn't on the map: " + "; ".join(lost) + ". Add them to the "
            "master layout with exactly these names."
        )
    _warn_missing("tables", missing_tables)


def _set_data_source(layer, gdb, feature_class):
    definition = layer.getDefinition("V3")
    connection = arcpy.cim.CreateCIMObjectFromClassName("CIMStandardDataConnection", "V3")
    connection.workspaceConnectionString = f"DATABASE={gdb}"
    connection.workspaceFactory = "FileGDB"
    connection.dataset = feature_class
    connection.datasetType = "esriDTFeatureClass"
    table = definition.featureTable
    table.dataConnection = connection
    # A definition query written for the template's old data could hide the
    # new features, so it goes.
    if getattr(table, "definitionExpression", None):
        table.definitionExpression = ""
    if getattr(table, "definitionFilterChoices", None):
        table.definitionFilterChoices = []
    if getattr(table, "definitionExpressionName", None):
        table.definitionExpressionName = ""
    layer.setDefinition(definition)


def _set_labels(layer, survey):
    """Points are labelled with their Name in the standard style; lines aren't
    labelled."""
    definition = layer.getDefinition("V3")
    if not survey.is_point:
        definition.labelVisibility = False
        layer.setDefinition(definition)
        return
    classes = list(definition.labelClasses or [])
    if not classes:
        arcpy.AddWarning(
            f"'{layer.name}' has no label class, so its points aren't labelled. "
            "Turn its labels on once in the master layout."
        )
        return
    label = classes[0]
    label.expressionEngine = "Arcade"
    label.expression = "$feature.Name"
    label.visibility = True
    text = label.textSymbol.symbol
    text.fontFamilyName = surveys.LABEL_FONT
    text.fontStyleName = surveys.LABEL_FONT_STYLE
    text.height = surveys.LABEL_SIZE_PT
    text.symbol = _fill_symbol(surveys.LABEL_COLOR)
    text.haloSymbol = _fill_symbol(surveys.HALO_COLOR)
    text.haloSize = surveys.HALO_SIZE_PT
    for other in classes[1:]:
        other.visibility = False
    definition.labelVisibility = True
    layer.setDefinition(definition)


def _fill_symbol(rgb):
    color = arcpy.cim.CreateCIMObjectFromClassName("CIMRGBColor", "V3")
    color.values = [rgb[0], rgb[1], rgb[2], 100]
    fill = arcpy.cim.CreateCIMObjectFromClassName("CIMSolidFill", "V3")
    fill.enable = True
    fill.color = color
    symbol = arcpy.cim.CreateCIMObjectFromClassName("CIMPolygonSymbol", "V3")
    symbol.symbolLayers = [fill]
    return symbol


def _set_table_fields(table):
    """Make the table show Name, X and Y, in that order, and nothing else."""
    fields = list(table.fields or [])
    shown = [surveys.normalise(f.name) for f in fields if getattr(f, "isVisible", True)]
    if shown == [name.casefold() for name in TABLE_FIELDS]:
        return
    by_name = {surveys.normalise(f.name): f for f in fields}
    ordered = []
    for name in TABLE_FIELDS:
        field = by_name.get(name.casefold())
        if field is None:
            field = _new_table_field(table, name)
        field.isVisible = True
        ordered.append(field)
    table.fields = ordered


def _new_table_field(table, name):
    field = None
    template = getattr(table, "defaultTableFrameField", None)
    if template is not None:
        try:
            field = copy.deepcopy(template)
        except Exception:
            field = None
    if field is None:
        field = arcpy.cim.CreateCIMObjectFromClassName("CIMTableFrameField", "V3")
    field.name = name
    return field


# --- Step 4: restyle the layout ---------------------------------------------


def restyle_layout(layout_name, gdb, spread=False):
    """Hide the layers, tables, headings and legend entries of surveys with no
    data, size each table to its rows and stack the tables in the tables
    panel."""
    gdb = check_geodatabase(gdb)
    layout = get_layout(current_project(), layout_name)
    frame = find_survey_map_frame(layout)
    layers = survey_layers(frame.map)
    present = present_surveys(gdb)
    if not present:
        raise surveys.SurveyMapError(
            f"There's no survey data in {gdb}. Run Step 1 Import Survey KMZ first."
        )
    points_per_unit = stacking.points_per_unit(layout.pageUnits)

    for code, layer in layers.items():
        layer.visible = code in present

    headings = {surveys.normalise(s.heading_name): s for s in surveys.point_surveys()}
    texts = {
        surveys.normalise(element.name): element
        for element in layout.listElements("TEXT_ELEMENT")
    }

    definition = layout.getDefinition("V3")
    elements = list(_walk(definition.elements))
    tables = {
        surveys.normalise(e.name): e for e in elements if _cim_type(e) == "CIMTableFrame"
    }
    anchors = {
        surveys.normalise(e.name): _anchor_name(getattr(e, "anchor", None)) for e in elements
    }
    panel_name = surveys.normalise(surveys.TABLES_PANEL_NAME)
    panel_element = next((e for e in elements if surveys.normalise(e.name) == panel_name), None)

    shown, hidden, missing, blocks = [], [], [], []
    for survey in surveys.point_surveys():
        table = tables.get(surveys.normalise(survey.table_name))
        heading = texts.get(surveys.normalise(survey.heading_name))
        if table is None:
            missing.append(survey.table_name)
        if heading is None:
            missing.append(survey.heading_name)
        if survey.code not in present:
            hidden.append(survey.code)
            if table is not None:
                table.visible = False
            continue
        shown.append(f"{survey.code} ({surveys.plural(present[survey.code], 'row')})")
        if table is None:
            continue
        table.visible = True
        bounds = _bounds(table)
        if bounds is None:
            continue
        block = stacking.Block(
            heading.elementWidth if heading is not None else 0.0,
            heading.elementHeight if heading is not None else 0.0,
            bounds[2] - bounds[0],
            _table_height_points(table, present[survey.code]) / points_per_unit,
        )
        blocks.append((bounds[3], survey, table, block))
    # Keep the order the tables have in the layout, top to bottom.
    blocks.sort(key=lambda item: -item[0])

    shown_layers = {
        layers[code].getDefinition("V3").uRI for code in layers if code in present
    }
    for legend in (e for e in elements if _cim_type(e) == "CIMLegend"):
        if getattr(legend, "mapFrame", None) != frame.name:
            continue
        for item in legend.items or []:
            item.isVisible = getattr(item, "layer", None) in shown_layers

    heading_spots = {}
    panel = _bounds(panel_element) if panel_element is not None else None
    if panel is None:
        arcpy.AddWarning(
            f"There's no rectangle called '{surveys.TABLES_PANEL_NAME}' in the "
            "layout, so the tables were resized where they are instead of being "
            "stacked."
        )
        for top, _survey, table, block in blocks:
            left = _bounds(table)[0]
            _set_frame(table, left, top - block.table_height, left + block.table_width, top)
    else:
        placements, scale = stacking.stack(
            panel,
            [block for _, _, _, block in blocks],
            margin=surveys.PANEL_MARGIN_PT / points_per_unit,
            heading_gap=surveys.HEADING_GAP_PT / points_per_unit,
            group_gap=surveys.GROUP_GAP_PT / points_per_unit,
            min_gap=surveys.MIN_GAP_PT / points_per_unit,
            spread=spread,
        )
        for (_top, survey, table, _block), placement in zip(blocks, placements):
            left, bottom, width, height = placement.table
            _set_frame(table, left, bottom, left + width, bottom + height)
            if placement.heading is not None:
                heading_spots[survey.code] = placement.heading
        if scale < 1.0:
            arcpy.AddWarning(
                f"The tables didn't all fit in '{surveys.TABLES_PANEL_NAME}', so "
                f"they were squeezed to {scale:.0%} of their full height and ArcGIS "
                "Pro will shrink their text to fit. If that's too small, make the "
                "panel taller or the table text smaller in the master layout."
            )
        if placements and placements[-1].table[1] < panel[1] - 1e-6:
            arcpy.AddWarning(
                f"The tables run past the bottom of '{surveys.TABLES_PANEL_NAME}'."
            )
    layout.setDefinition(definition)

    # Headings are moved after the layout definition is saved, so the two
    # don't overwrite each other.
    for element in layout.listElements("TEXT_ELEMENT"):
        survey = headings.get(surveys.normalise(element.name))
        if survey is None:
            continue
        element.visible = survey.code in present
        spot = heading_spots.get(survey.code)
        if spot is not None:
            anchor = anchors.get(surveys.normalise(element.name)) or "BottomLeftCorner"
            x, y = stacking.anchor_point(
                anchor, spot[0], spot[1], element.elementWidth, element.elementHeight
            )
            element.elementPositionX = x
            element.elementPositionY = y

    arcpy.AddMessage("Showing: " + ", ".join(shown))
    if hidden:
        arcpy.AddMessage("Hidden, not in this KMZ: " + ", ".join(hidden))
    if panel is not None:
        how = "spread evenly" if spread else "stacked from the top"
        arcpy.AddMessage(f"Tables {how} in '{surveys.TABLES_PANEL_NAME}'.")
    _warn_missing("tables and headings", missing)


def _table_height_points(table, rows):
    fields = list(table.fields or [])
    field = fields[0] if fields else getattr(table, "defaultTableFrameField", None)
    text_size = _text_size(getattr(field, "textSymbol", None), 10.0)
    heading_size = _text_size(getattr(field, "headingTextSymbol", None), text_size)
    return stacking.table_height_points(
        rows,
        text_size,
        heading_size,
        vertical_gap=float(getattr(table, "verticalTextGap", 0) or 0),
        row_gap=float(getattr(table, "rowGap", 0) or 0),
        heading_gap=float(getattr(table, "headingGap", 0) or 0),
        show_headings=bool(getattr(table, "showHeadings", True)),
        columns=getattr(table, "columns", 1) or 1,
    )


def _text_size(symbol_reference, default):
    height = getattr(getattr(symbol_reference, "symbol", None), "height", None)
    return float(height) if height else default


# --- CIM helpers ------------------------------------------------------------


def _cim_type(cim_object):
    return type(cim_object).__name__


def _walk(elements):
    """Every layout element, including those inside group elements."""
    for element in elements or []:
        yield element
        children = getattr(element, "elements", None)
        if children:
            yield from _walk(children)


def _elements_by_name(definition, cim_type):
    return {
        surveys.normalise(element.name): element
        for element in _walk(definition.elements)
        if _cim_type(element) == cim_type
    }


def _anchor_name(value):
    """'TopLeftCorner' from a CIM anchor, whether it comes back as a string,
    'Anchor.TopLeftCorner' or an enum member."""
    if value is None:
        return None
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return str(value).split(".")[-1]


def _points(geometry):
    if geometry is None:
        return []
    if isinstance(geometry, dict):
        if "x" in geometry and "y" in geometry:
            return [(geometry["x"], geometry["y"])]
        parts = geometry.get("rings") or geometry.get("paths") or []
    else:
        parts = getattr(geometry, "rings", None) or getattr(geometry, "paths", None) or []
    return [(point[0], point[1]) for part in parts for point in part]


def _bounds(element):
    """(x_min, y_min, x_max, y_max) of a layout element on the page, or None."""
    points = _points(getattr(element, "frame", None))
    if not points:
        graphic = getattr(element, "graphic", None)
        for attribute in ("polygon", "shape", "line"):
            points = _points(getattr(graphic, attribute, None))
            if points:
                break
    if not points:
        return None
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def _set_frame(element, left, bottom, right, top):
    rings = [[[left, bottom], [left, top], [right, top], [right, bottom], [left, bottom]]]
    frame = element.frame
    if isinstance(frame, dict):
        frame = dict(frame)
        frame["rings"] = rings
        element.frame = frame
    else:
        frame.rings = rings
    # ArcGIS Pro keeps the rotation centre on the element's anchor.
    anchor = _anchor_name(getattr(element, "anchor", None))
    x, y = stacking.anchor_point(anchor, left, bottom, right - left, top - bottom)
    centre = getattr(element, "rotationCenter", None)
    if isinstance(centre, dict):
        centre = dict(centre)
        centre.update(x=x, y=y)
        element.rotationCenter = centre
    elif centre is not None:
        centre.x, centre.y = x, y


def _warn_missing(what, names):
    if names:
        arcpy.AddWarning(
            f"These {what} aren't in the layout, so they were skipped: "
            + ", ".join(names)
            + ". Name them as in the README if they should be."
        )
