# -*- coding: utf-8 -*-
"""Steps 4 and 5: connect the survey data to the master layout, then tidy the
layout so it only shows the surveys that are present.

The layout's layers, tables and headings are found by name; see README.md for
the names the master layout needs.
"""

import copy
import json
import os

import arcpy

from . import gis, stacking, surveys

TABLE_FIELDS = ("Name", "X", "Y")
XY_FIELDS = ("x", "y")


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
        try:
            survey = wanted.get(surveys.normalise(layer.name))
            if survey is None or survey.code in found:
                continue
            if layer.isFeatureLayer or _cim_type(layer.getDefinition("V3")) == "CIMFeatureLayer":
                found[survey.code] = layer
        except Exception:
            continue  # A layer that can't be read isn't one the tools can use.
    return found


def _correct_spelling(layout, layers):
    """Correct old spellings, such as 'Snorkelling', in the survey layer names
    (which are also the legend text) and in the table headings."""
    corrected = []
    for layer in layers.values():
        with gis.carry_on("correct the spelling of a survey layer's name",
                          so="it keeps the old spelling"):
            old = layer.name
            new = surveys.fix_spelling(old)
            if new != old:
                layer.name = new
                corrected.append(f"'{new}'")
    headings = {surveys.normalise(s.heading_name) for s in surveys.point_surveys()}
    with gis.carry_on("correct the spelling in the table headings",
                      so="they keep the old spelling"):
        for element in layout.listElements("TEXT_ELEMENT"):
            if surveys.normalise(element.name) not in headings:
                continue
            old = element.text
            new = surveys.fix_spelling(old)
            if new != old:
                element.text = new
                corrected.append(element.name)
    if corrected:
        arcpy.AddMessage("Corrected the spelling in: " + ", ".join(corrected) + ".")


def find_survey_map_frame(layout):
    """The map frame showing the map with the most survey layers in it."""
    best_key = best = None
    for frame in layout.listElements("MAPFRAME_ELEMENT"):
        try:
            map_ = frame.map
            if map_ is None:
                continue
            found = len(survey_layers(map_))
            if not found:
                continue
            key = (found, bool(frame.visible), frame.elementWidth * frame.elementHeight)
        except Exception:
            continue  # A frame that can't be read isn't showing the survey map.
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
        with gis.carry_on(f"count the features in {survey.feature_class}",
                          so="it's left off the map"):
            if arcpy.Exists(path):
                count = gis.count(path)
                if count:
                    counts[survey.code] = count
    return counts


def _surveys_to_show(gdb, present):
    """The surveys to show: present (survey code -> feature count) when the
    all-in-one tool passes on what it just made, otherwise what's in gdb."""
    present = present_surveys(gdb) if present is None else dict(present)
    if not present:
        raise surveys.SurveyMapError(
            f"There's no survey data to map in {gdb}. Check that Step 1 Import "
            "Survey KMZ found survey points in the KMZ."
        )
    return present


# --- Step 4: connect the data -----------------------------------------------


def connect_data(layout_name, gdb, present=None):
    """Point each survey layer in the layout's map at its feature class in gdb,
    link each survey's table to its layer and set the point labels. Surveys
    with no data are turned off.

    present (survey code -> feature count) says which surveys to connect; it
    defaults to the ones with data in gdb. A layer or table that can't be
    changed is skipped with a warning. Returns the surveys now on the map, as
    survey code -> feature count.
    """
    gdb = check_geodatabase(gdb)
    layout = get_layout(current_project(), layout_name)
    frame = find_survey_map_frame(layout)
    layers = survey_layers(frame.map)
    present = _surveys_to_show(gdb, present)
    arcpy.AddMessage(f"Survey map: '{frame.map.name}', shown in map frame '{frame.name}'.")
    _correct_spelling(layout, layers)

    arrows = surveys.by_code(surveys.CURRENT_ARROWS)
    if arrows.code in present and arrows.code not in layers:
        with gis.carry_on(f"add the '{arrows.layer_name}' layer to the survey map",
                          so="the currents show as points") as outcome:
            layers[arrows.code] = _add_arrows_layer(frame.map, gdb, layers)
            arcpy.AddMessage(
                f"Added the '{arrows.layer_name}' layer to the survey map, drawn as "
                "arrows. To change how it looks, restyle it and save it in the master "
                "layout; the tools keep its style from then on."
            )
        if not outcome.ok:
            del present[arrows.code]
    shown = surveys.layers_to_show(present)

    connected, turned_off, failed, decimals = [], [], [], {}
    for survey in surveys.SURVEYS:
        layer = layers.get(survey.code)
        if layer is None:
            continue
        if survey.code not in present:
            with gis.carry_on(f"turn off '{survey.layer_name}'"):
                layer.visible = False
            turned_off.append(survey.layer_name)
            continue
        with gis.carry_on(f"connect '{survey.layer_name}' to {survey.feature_class}",
                          so="the layer is turned off") as outcome:
            _set_data_source(layer, gdb, survey.feature_class)
            layer.visible = survey.code in shown
        if not outcome.ok:
            failed.append(survey.code)
            _turn_off(layer)
            continue
        with gis.carry_on(f"set the labels on '{survey.layer_name}'"):
            _set_labels(layer, survey)
        if survey.is_point:
            decimals[survey.code] = _xy_decimals(os.path.join(gdb, survey.feature_class))
            with gis.carry_on(f"set how '{survey.layer_name}' shows X and Y"):
                _set_xy_format(layer, decimals[survey.code])
        connected.append(f"{survey.layer_name} ({present[survey.code]})")
    for code in failed:
        del present[code]
    # If the arrows couldn't be connected, the current points go back on.
    still_shown = surveys.layers_to_show(present)
    for code in still_shown - shown:
        if code in layers:
            with gis.carry_on(f"turn on '{surveys.by_code(code).layer_name}'"):
                layers[code].visible = True
    shown = still_shown
    if failed and not connected:
        raise surveys.SurveyMapError(
            "None of the survey layers could be connected to the new data, so "
            "the tool stopped. The warnings above say why."
        )

    missing_tables = []
    with gis.carry_on("link the tables to their layers", so="they keep their old links"):
        definition = layout.getDefinition("V3")
        tables = _elements_by_name(definition, "CIMTableFrame")
        for survey in surveys.point_surveys():
            table = tables.get(surveys.normalise(survey.table_name))
            layer = layers.get(survey.code)
            if table is None:
                missing_tables.append(survey.table_name)
            elif layer is not None:
                with gis.carry_on(f"link {survey.table_name} to '{survey.layer_name}'"):
                    table.mapFrame = frame.name
                    table.mapMemberURI = layer.getDefinition("V3").uRI
                    _set_table_fields(table)
                with gis.carry_on(f"set the X and Y decimals in {survey.table_name}"):
                    _set_table_decimals(table, decimals.get(survey.code, surveys.XY_DECIMALS))
        layout.setDefinition(definition)

    if connected:
        arcpy.AddMessage("Connected: " + "; ".join(connected))
    if turned_off:
        arcpy.AddMessage("Turned off, no data to show: " + "; ".join(turned_off))
    points = surveys.by_code(surveys.CURRENT_POINTS)
    if points.code in present and points.code not in shown and points.code in layers:
        arcpy.AddMessage(
            f"The currents show as arrows, so '{points.layer_name}' is turned off. "
            f"Its points still fill {points.table_name}."
        )
    lost = [s.layer_name for s in surveys.SURVEYS if s.code in present and s.code not in layers]
    if lost:
        arcpy.AddWarning(
            "This KMZ has data for layers the survey map doesn't have, so that "
            "data isn't on the map: " + "; ".join(lost) + ". Add them to the "
            "master layout with exactly these names."
        )
    _warn_missing("tables", missing_tables)
    return present


def _add_arrows_layer(map_, gdb, layers):
    """Add the current arrows to the survey map, drawn as arrows, above the
    current points. Returns the new layer."""
    survey = surveys.by_code(surveys.CURRENT_ARROWS)
    layer = map_.addDataFromPath(os.path.join(gdb, survey.feature_class))
    layer.name = survey.layer_name
    definition = layer.getDefinition("V3")
    renderer = getattr(definition, "renderer", None)
    if _cim_type(renderer) == "CIMSimpleRenderer" and getattr(renderer, "symbol", None) is not None:
        renderer.symbol.symbol = _arrow_symbol()
    else:
        reference = arcpy.cim.CreateCIMObjectFromClassName("CIMSymbolReference", "V3")
        reference.symbol = _arrow_symbol()
        renderer = arcpy.cim.CreateCIMObjectFromClassName("CIMSimpleRenderer", "V3")
        renderer.symbol = reference
        definition.renderer = renderer
    layer.setDefinition(definition)
    points = layers.get(surveys.CURRENT_POINTS)
    if points is not None:
        try:
            map_.moveLayer(points, layer, "BEFORE")
        except Exception:
            pass  # Where it sits in the Contents pane doesn't matter.
    return layer


def _arrow_symbol():
    """A line with an edge, and an arrowhead at its end."""
    head = arcpy.cim.CreateCIMObjectFromClassName("CIMVectorMarker", "V3")
    head.enable = True
    head.size = surveys.ARROWHEAD_SIZE_PT
    head.anchorPointUnits = "Relative"
    head.frame = {"xmin": -5.0, "ymin": -5.0, "xmax": 5.0, "ymax": 5.0}
    head.respectFrame = True
    head.scaleSymbolsProportionally = True
    graphic = arcpy.cim.CreateCIMObjectFromClassName("CIMMarkerGraphic", "V3")
    # A triangle pointing along the line.
    graphic.geometry = {"rings": [[[5.0, 0.0], [-5.0, 4.0], [-5.0, -4.0], [5.0, 0.0]]]}
    fill = _fill_symbol(surveys.ARROW_COLOR)
    fill.symbolLayers = [
        _stroke(surveys.ARROW_EDGE_COLOR, surveys.ARROW_EDGE_PT)
    ] + list(fill.symbolLayers)
    graphic.symbol = fill
    head.markerGraphics = [graphic]
    placement = arcpy.cim.CreateCIMObjectFromClassName("CIMMarkerPlacementAtExtremities", "V3")
    placement.angleToLine = True
    placement.extremityPlacement = "JustEnd"
    head.markerPlacement = placement

    symbol = arcpy.cim.CreateCIMObjectFromClassName("CIMLineSymbol", "V3")
    symbol.symbolLayers = [
        head,
        _stroke(surveys.ARROW_COLOR, surveys.ARROW_WIDTH_PT),
        _stroke(surveys.ARROW_EDGE_COLOR, surveys.ARROW_WIDTH_PT + 2 * surveys.ARROW_EDGE_PT),
    ]
    return symbol


def _stroke(rgb, width):
    stroke = arcpy.cim.CreateCIMObjectFromClassName("CIMSolidStroke", "V3")
    stroke.enable = True
    stroke.capStyle = "Round"
    stroke.joinStyle = "Round"
    stroke.miterLimit = 10
    stroke.width = width
    stroke.color = _rgb_color(rgb)
    return stroke


def _turn_off(layer):
    try:
        layer.visible = False
    except Exception:
        pass


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
    """Points are labelled with their Name in the standard style, and current
    arrows with their speed and direction; other lines aren't labelled."""
    definition = layer.getDefinition("V3")
    field = surveys.label_field(survey)
    if field is None:
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
    label.expression = f"$feature.{field}"
    # A SQL query or scale range left on the label class would hide labels.
    # Layers first made from KML often have the query "LabelID" = 0, and the
    # survey data has no LabelID field, so those points went unlabelled.
    label.whereClause = ""
    label.minimumScale = 0
    label.maximumScale = 0
    label.visibility = True
    text = label.textSymbol.symbol
    text.fontFamilyName = surveys.LABEL_FONT
    text.fontStyleName = surveys.LABEL_FONT_STYLE
    text.height = surveys.LABEL_SIZE_PT
    text.symbol = _fill_symbol(surveys.LABEL_COLOR)
    text.haloSymbol = _fill_symbol(surveys.HALO_COLOR)
    text.haloSize = surveys.HALO_SIZE_PT
    if not survey.is_point:
        _place_along_line(label)
    for other in classes[1:]:
        other.visibility = False
    definition.labelVisibility = True
    layer.setDefinition(definition)


def _place_along_line(label):
    """Label a line along it, even when the line is shorter than the label, as
    a current arrow often is."""
    placement = getattr(label, "maplexLabelPlacementProperties", None)
    if placement is None:
        return
    placement.linePlacementMethod = "OffsetStraightFromLine"
    placement.constrainOffset = "AboveLine"
    placement.canOverrunFeature = True
    placement.maximumLabelOverrun = 200
    placement.maximumLabelOverrunUnit = "Point"
    placement.neverRemoveLabel = True


def _rgb_color(rgb):
    color = arcpy.cim.CreateCIMObjectFromClassName("CIMRGBColor", "V3")
    color.values = [rgb[0], rgb[1], rgb[2], 100]
    return color


def _fill_symbol(rgb):
    fill = arcpy.cim.CreateCIMObjectFromClassName("CIMSolidFill", "V3")
    fill.enable = True
    fill.color = _rgb_color(rgb)
    symbol = arcpy.cim.CreateCIMObjectFromClassName("CIMPolygonSymbol", "V3")
    symbol.symbolLayers = [fill]
    return symbol


def _xy_decimals(path):
    """Decimal places to show X and Y with: 6 when they're in degrees."""
    try:
        with arcpy.da.SearchCursor(path, ["X"]) as rows:
            for (x,) in rows:
                if x is not None:
                    return surveys.XY_DECIMALS_DEGREES if abs(x) <= 180 else surveys.XY_DECIMALS
    except Exception:
        pass
    return surveys.XY_DECIMALS


def _number_format(decimals):
    """Exactly decimals places, so 281308 shows as 281308.00."""
    number_format = arcpy.cim.CreateCIMObjectFromClassName("CIMNumericFormat", "V3")
    number_format.roundingOption = "esriRoundNumberOfDecimals"
    number_format.roundingValue = decimals
    number_format.zeroPad = True
    number_format.useSeparator = False
    return number_format


def _set_xy_format(layer, decimals):
    """Show X and Y to decimals places in the layer's attribute table and
    pop-ups. The master's layers keep formats from older data, with 3 or 6
    places and no zero padding."""
    definition = layer.getDefinition("V3")
    table = getattr(definition, "featureTable", None)
    changed = False
    for description in getattr(table, "fieldDescriptions", None) or []:
        if surveys.normalise(getattr(description, "fieldName", None)) in XY_FIELDS:
            description.numberFormat = _number_format(decimals)
            changed = True
    if changed:
        layer.setDefinition(definition)


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


def _set_table_decimals(table, decimals):
    """Show X and Y in the table to exactly decimals places. Without this the
    table uses the layer's format, so 281308.0 showed as 281308 next to
    278648.612."""
    fields = list(table.fields or [])
    for field in fields:
        if surveys.normalise(field.name) in XY_FIELDS:
            field.numberFormat = _number_format(decimals)
    table.fields = fields


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


# --- Step 5: restyle the layout ---------------------------------------------


def restyle_layout(layout_name, gdb, spread=False, present=None):
    """Hide the layers, tables, headings and legend entries of surveys with no
    data, size each table to its rows and stack the tables in the tables
    panel.

    present (survey code -> feature count) says which surveys to show; it
    defaults to the ones with data in gdb. Anything that can't be changed is
    skipped with a warning.
    """
    gdb = check_geodatabase(gdb)
    layout = get_layout(current_project(), layout_name)
    frame = find_survey_map_frame(layout)
    layers = survey_layers(frame.map)
    present = _surveys_to_show(gdb, present)
    points_per_unit = stacking.points_per_unit(layout.pageUnits)
    _correct_spelling(layout, layers)

    arrows = surveys.by_code(surveys.CURRENT_ARROWS)
    if arrows.code in present and arrows.code not in layers:
        arcpy.AddWarning(
            f"There are current arrows in {gdb}, but the survey map has no "
            f"'{arrows.layer_name}' layer yet, so the current points are shown "
            "instead. Run Step 4 Connect Data to Layout to add it."
        )
        present = {code: n for code, n in present.items() if code != arrows.code}
    shown_layers = surveys.layers_to_show(present)

    for code, layer in layers.items():
        show = code in shown_layers
        with gis.carry_on(f"{'show' if show else 'hide'} '{surveys.by_code(code).layer_name}'"):
            layer.visible = show

    shown = [
        f"{s.code} ({surveys.plural(present[s.code], 'row')})"
        for s in surveys.point_surveys() if s.code in present
    ]
    hidden = [s.code for s in surveys.point_surveys() if s.code not in present]
    headings = {surveys.normalise(s.heading_name): s for s in surveys.point_surveys()}
    texts = {
        surveys.normalise(element.name): element
        for element in layout.listElements("TEXT_ELEMENT")
    }

    missing, anchors, heading_spots, panel = [], {}, {}, None
    with gis.carry_on("resize and stack the tables", so="they're left as they were") as tables:
        definition = layout.getDefinition("V3")
        elements = list(_walk(definition.elements))
        table_elements = {
            surveys.normalise(e.name): e for e in elements if _cim_type(e) == "CIMTableFrame"
        }
        anchors = {
            surveys.normalise(e.name): _anchor_name(getattr(e, "anchor", None)) for e in elements
        }
        panel_name = surveys.normalise(surveys.TABLES_PANEL_NAME)
        panel_element = next((e for e in elements if surveys.normalise(e.name) == panel_name), None)

        blocks = []
        for survey in surveys.point_surveys():
            table = table_elements.get(surveys.normalise(survey.table_name))
            heading = texts.get(surveys.normalise(survey.heading_name))
            if table is None:
                missing.append(survey.table_name)
            if heading is None:
                missing.append(survey.heading_name)
            if table is None:
                continue
            if survey.code not in present:
                table.visible = False
                continue
            table.visible = True
            with gis.carry_on(f"size {survey.table_name}", so="it's left as it was"):
                bounds = _bounds(table)
                if bounds is None:
                    raise surveys.SurveyMapError(
                        f"Couldn't find where {survey.table_name} is on the page."
                    )
                block = stacking.Block(
                    heading.elementWidth if heading is not None else 0.0,
                    heading.elementHeight if heading is not None else 0.0,
                    bounds[2] - bounds[0],
                    _table_height_points(table, present[survey.code]) / points_per_unit,
                )
                blocks.append((bounds[3], survey, table, block))
        # Keep the order the tables have in the layout, top to bottom.
        blocks.sort(key=lambda item: -item[0])

        with gis.carry_on("update the legend"):
            _update_legends(elements, frame, layers, shown_layers)

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
    # don't overwrite each other. If the tables couldn't be saved, the
    # headings stay next to them.
    for element in layout.listElements("TEXT_ELEMENT"):
        survey = headings.get(surveys.normalise(element.name))
        if survey is None:
            continue
        show = survey.code in present
        with gis.carry_on(f"{'show' if show else 'hide'} {survey.heading_name}"):
            element.visible = show
        spot = heading_spots.get(survey.code) if tables.ok else None
        if spot is None:
            continue
        with gis.carry_on(f"move {survey.heading_name}", so="it's left where it was"):
            anchor = anchors.get(surveys.normalise(element.name)) or "BottomLeftCorner"
            x, y = stacking.anchor_point(
                anchor, spot[0], spot[1], element.elementWidth, element.elementHeight
            )
            element.elementPositionX = x
            element.elementPositionY = y

    arcpy.AddMessage("Showing: " + ", ".join(shown))
    if arrows.code in shown_layers:
        arcpy.AddMessage(
            f"Currents show as arrows labelled with their speed and direction "
            f"({surveys.plural(present[arrows.code], 'arrow')})."
        )
    if hidden:
        arcpy.AddMessage("Hidden, no data to show: " + ", ".join(hidden))
    if tables.ok and panel is not None:
        how = "spread evenly" if spread else "stacked from the top"
        arcpy.AddMessage(f"Tables {how} in '{surveys.TABLES_PANEL_NAME}'.")
    _warn_missing("tables and headings", missing)


def _update_legends(elements, frame, layers, shown):
    """Show only the survey layers on the map (codes in shown) in the survey
    map's legends. The current arrows get a legend entry next to the current
    points' if ArcGIS Pro hasn't added one."""
    uris = {code: layers[code].getDefinition("V3").uRI for code in layers}
    shown_layers = {uri for code, uri in uris.items() if code in shown}
    for legend in (e for e in elements if _cim_type(e) == "CIMLegend"):
        if getattr(legend, "mapFrame", None) != frame.name:
            continue
        items = list(legend.items or [])
        arrows = uris.get(surveys.CURRENT_ARROWS)
        if arrows in shown_layers and arrows not in [getattr(i, "layer", None) for i in items]:
            items = _with_legend_item(
                items, arrows, layers[surveys.CURRENT_ARROWS].name,
                after=uris.get(surveys.CURRENT_POINTS),
            )
        for item in items:
            item.isVisible = getattr(item, "layer", None) in shown_layers
            if getattr(item, "name", None):
                item.name = surveys.fix_spelling(item.name)
        legend.items = items


def _with_legend_item(items, uri, name, after=None):
    """items with a new entry for the layer uri, styled like the entry for the
    layer after (or the last entry) and placed just after it."""
    index = next(
        (n for n, item in enumerate(items) if getattr(item, "layer", None) == after),
        len(items) - 1,
    )
    item = None
    if items:
        try:
            item = copy.deepcopy(items[index])
        except Exception:
            item = None
    if item is None:
        item = arcpy.cim.CreateCIMObjectFromClassName("CIMLegendItem", "V3")
    item.name = name
    item.layer = uri
    return items[:index + 1] + [item] + items[index + 1:]


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


def _geometry_dict(geometry):
    """A CIM geometry as an Esri JSON dict, or None. ArcGIS Pro hands most
    back as dicts, but ones saved with a spatial reference (as some of the
    master's tables are) come back as geometry objects."""
    if geometry is None or isinstance(geometry, dict):
        return geometry
    try:
        text = getattr(geometry, "JSON", None)
        if isinstance(text, str):
            return json.loads(text)
    except Exception:
        pass
    for attribute in ("rings", "paths"):
        parts = getattr(geometry, attribute, None)
        if parts:
            return {attribute: parts}
    x, y = getattr(geometry, "x", None), getattr(geometry, "y", None)
    if x is not None and y is not None:
        return {"x": x, "y": y}
    try:
        e = geometry.extent
        corners = [[e.XMin, e.YMin], [e.XMin, e.YMax], [e.XMax, e.YMax], [e.XMax, e.YMin]]
        return {"rings": [corners + corners[:1]]}
    except Exception:
        return None


def _points(geometry):
    geometry = _geometry_dict(geometry)
    if not geometry:
        return []
    if geometry.get("x") is not None and geometry.get("y") is not None:
        return [(geometry["x"], geometry["y"])]
    parts = geometry.get("rings") or geometry.get("paths") or []
    return [
        (point[0], point[1])
        for part in parts
        for point in part
        if isinstance(point, (list, tuple)) and len(point) >= 2
    ]


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
    """Move and size an element. The frame and rotation centre are written
    as dicts even when ArcGIS Pro handed them over as geometry objects; the
    dict form is the one that works for every table."""
    rings = [[[left, bottom], [left, top], [right, top], [right, bottom], [left, bottom]]]
    frame = getattr(element, "frame", None)
    frame = dict(frame) if isinstance(frame, dict) else {}
    frame["rings"] = rings
    element.frame = frame
    # ArcGIS Pro keeps the rotation centre on the element's anchor.
    anchor = _anchor_name(getattr(element, "anchor", None))
    x, y = stacking.anchor_point(anchor, left, bottom, right - left, top - bottom)
    centre = getattr(element, "rotationCenter", None)
    if centre is not None:
        centre = dict(centre) if isinstance(centre, dict) else {}
        centre.update(x=x, y=y)
        element.rotationCenter = centre


def _warn_missing(what, names):
    if names:
        arcpy.AddWarning(
            f"These {what} aren't in the layout, so they were skipped: "
            + ", ".join(names)
            + ". Name them as in the README if they should be."
        )
