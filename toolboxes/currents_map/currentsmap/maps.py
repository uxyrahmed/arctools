# -*- coding: utf-8 -*-
"""Step 2: show the currents on a map in the open project, drawn as arrows
and labelled with their speed and direction, and zoom to them."""

import os

import arcpy

from . import arrows, common, gis, messages

# Degrees to metres at the equator, for zooming a map that's in degrees.
METRES_PER_DEGREE = 111320.0


# --- Finding things ---------------------------------------------------------


def current_project():
    try:
        return arcpy.mp.ArcGISProject("CURRENT")
    except Exception:
        raise common.CurrentsMapError(
            "Run this tool from ArcGIS Pro, with the project that holds the map open."
        )


def map_choices():
    """(map names, default name) for the open project, or ([], None) when no
    project is open. The default is the map open now, else the one that
    already has a Currents layer, else the only map."""
    try:
        aprx = arcpy.mp.ArcGISProject("CURRENT")
        maps = aprx.listMaps()
        names = [map_.name for map_ in maps]
    except Exception:
        return [], None
    default = None
    try:
        view = aprx.activeView
        if view is not None and hasattr(view, "camera") and getattr(view, "map", None):
            default = view.map.name
    except Exception:
        pass
    if default is None:
        with_currents = [m.name for m in maps if _find_layer(m, common.ARROWS_LAYER_NAME)]
        if len(with_currents) == 1:
            default = with_currents[0]
        elif len(names) == 1:
            default = names[0]
    return names, default


def get_map(aprx, name):
    for map_ in aprx.listMaps():
        if map_.name == name:
            return map_
    raise common.CurrentsMapError(f"There's no map called '{name}' in this project.")


def _find_layer(map_, name):
    """The first feature layer in map_ called name (case doesn't matter)."""
    wanted = common.normalise(name)
    try:
        layers = map_.listLayers()
    except Exception:
        return None
    for layer in layers:
        try:
            if common.normalise(layer.name) == wanted and layer.isFeatureLayer:
                return layer
        except Exception:
            continue
    return None


# --- Showing the currents ---------------------------------------------------


def add_to_map(gdb, map_name, show_points=False, zoom=True):
    """Show the current arrows in gdb on the map called map_name, as a layer
    called Currents labelled with each current's speed and direction. A
    Currents layer that's already in the map is pointed at gdb and keeps its
    style; otherwise one is added, drawn as white arrows with a black edge.

    show_points also shows each current's start and end point, labelled with
    its name. zoom zooms the map to the currents when it's the map open now.
    """
    gdb = arrows.check_geodatabase(gdb)
    path = arrows.arrows_path(gdb)
    if not arcpy.Exists(path):
        raise common.CurrentsMapError(
            f"There are no current arrows in {gdb}. Run Step 1 Draw Current Arrows first."
        )
    count = gis.count(path)
    if not count:
        arcpy.AddWarning(f"{common.ARROWS_FEATURE_CLASS} in {gdb} has no arrows in it.")
    aprx = current_project()
    map_ = get_map(aprx, map_name)

    layer = _show_layer(
        map_, gdb, common.ARROWS_FEATURE_CLASS, common.ARROWS_LAYER_NAME, _style_arrows,
    )
    with gis.carry_on(f"label '{layer.name}' with the speed and direction"):
        _set_labels(layer, "Label", along_line=True)

    points_path = arrows.points_path(gdb)
    points = _find_layer(map_, common.POINTS_LAYER_NAME)
    if show_points and not arcpy.Exists(points_path):
        arcpy.AddWarning(
            f"There are no start and end points in {gdb}, so only the arrows are "
            "shown. Run Step 1 again to make them."
        )
    elif show_points:
        with gis.carry_on(f"show the start and end points as '{common.POINTS_LAYER_NAME}'"):
            points = _show_layer(
                map_, gdb, common.POINTS_FEATURE_CLASS, common.POINTS_LAYER_NAME,
                _style_points,
            )
            with gis.carry_on(f"label '{points.name}' with the point names"):
                _set_labels(points, "Name")
            try:
                map_.moveLayer(layer, points, "AFTER")
            except Exception:
                pass  # Where it sits in the Contents pane doesn't matter much.
    elif points is not None:
        with gis.carry_on(f"turn off '{points.name}'"):
            if arcpy.Exists(points_path):
                _set_data_source(points, gdb, common.POINTS_FEATURE_CLASS)
            points.visible = False

    arcpy.AddMessage(
        f"'{map_.name}' shows {common.plural(count, 'current')} as arrows labelled "
        "with their speed and direction."
    )
    if zoom:
        with gis.carry_on("zoom to the currents"):
            _zoom_to(aprx, map_, path)
    return count


def _show_layer(map_, gdb, feature_class, layer_name, style):
    """The layer called layer_name in map_, pointed at gdb's feature_class and
    turned on. Added and styled with style(layer) if the map hasn't one."""
    layer = _find_layer(map_, layer_name)
    if layer is not None:
        gis.retry_on_lock(_set_data_source, layer, gdb, feature_class)
        layer.visible = True
        arcpy.AddMessage(f"Pointed '{layer.name}' at {feature_class}, keeping its style.")
        return layer
    try:
        layer = map_.addDataFromPath(os.path.join(gdb, feature_class))
        layer.name = layer_name
    except Exception as error:
        raise common.CurrentsMapError(
            messages.problem(error, f"add '{layer_name}' to '{map_.name}'")
        ) from error
    with gis.carry_on(f"style '{layer_name}'", so="it has ArcGIS Pro's default style"):
        style(layer)
    arcpy.AddMessage(
        f"Added '{layer_name}' to '{map_.name}'. Restyle it there if you like; "
        "the tools keep its style from then on."
    )
    return layer


def _zoom_to(aprx, map_, path):
    """Zoom the map to the currents if it's the map open now."""
    view = aprx.activeView
    if view is None or not hasattr(view, "camera") or getattr(view, "map", None) is None:
        arcpy.AddMessage("Open the map to zoom to the currents; it isn't open now.")
        return
    if view.map.name != map_.name:
        arcpy.AddMessage(f"'{map_.name}' isn't the map open now, so it wasn't zoomed.")
        return
    extent = arcpy.Describe(path).extent
    sr = map_.spatialReference
    if sr is not None and sr.name and not gis.same_spatial_reference(extent.spatialReference, sr):
        extent = extent.projectAs(sr)
    per_unit = METRES_PER_DEGREE if sr is None or sr.type != "Projected" else sr.metersPerUnit
    xmin, ymin, xmax, ymax = common.zoom_extent(
        extent.XMin, extent.YMin, extent.XMax, extent.YMax, per_unit
    )
    view.camera.setExtent(arcpy.Extent(xmin, ymin, xmax, ymax, spatial_reference=extent.spatialReference))


# --- Data sources and labels ------------------------------------------------


def _cim_type(obj):
    return type(obj).__name__ if obj is not None else None


def _set_data_source(layer, gdb, feature_class):
    definition = layer.getDefinition("V3")
    connection = arcpy.cim.CreateCIMObjectFromClassName("CIMStandardDataConnection", "V3")
    connection.workspaceConnectionString = f"DATABASE={gdb}"
    connection.workspaceFactory = "FileGDB"
    connection.dataset = feature_class
    connection.datasetType = "esriDTFeatureClass"
    table = definition.featureTable
    table.dataConnection = connection
    # A definition query written for older data could hide the new features.
    if getattr(table, "definitionExpression", None):
        table.definitionExpression = ""
    if getattr(table, "definitionFilterChoices", None):
        table.definitionFilterChoices = []
    if getattr(table, "definitionExpressionName", None):
        table.definitionExpressionName = ""
    layer.setDefinition(definition)


def _set_labels(layer, field, along_line=False):
    """Label layer with field in white Tahoma with a black halo."""
    definition = layer.getDefinition("V3")
    classes = list(definition.labelClasses or [])
    if not classes:
        arcpy.AddWarning(
            f"'{layer.name}' has no label class, so it isn't labelled. Turn its "
            "labels on once in the map, then run this tool again."
        )
        return
    label = classes[0]
    label.expressionEngine = "Arcade"
    label.expression = f"$feature.{field}"
    label.whereClause = ""
    label.minimumScale = 0
    label.maximumScale = 0
    label.visibility = True
    text = label.textSymbol.symbol
    text.fontFamilyName = common.LABEL_FONT
    text.fontStyleName = common.LABEL_FONT_STYLE
    text.height = common.LABEL_SIZE_PT
    text.symbol = _fill_symbol(common.LABEL_COLOR)
    text.haloSymbol = _fill_symbol(common.HALO_COLOR)
    text.haloSize = common.HALO_SIZE_PT
    if along_line:
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


# --- Symbols ----------------------------------------------------------------


def _style_arrows(layer):
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


def _style_points(layer):
    symbology = layer.symbology
    symbol = symbology.renderer.symbol
    symbol.color = {"RGB": list(common.ARROW_COLOR) + [100]}
    symbol.outlineColor = {"RGB": list(common.ARROW_EDGE_COLOR) + [100]}
    symbol.size = common.POINT_SIZE_PT
    layer.symbology = symbology


def _arrow_symbol():
    """A line with an edge, and an arrowhead at its end."""
    head = arcpy.cim.CreateCIMObjectFromClassName("CIMVectorMarker", "V3")
    head.enable = True
    head.size = common.ARROWHEAD_SIZE_PT
    head.anchorPointUnits = "Relative"
    head.frame = {"xmin": -5.0, "ymin": -5.0, "xmax": 5.0, "ymax": 5.0}
    head.respectFrame = True
    head.scaleSymbolsProportionally = True
    graphic = arcpy.cim.CreateCIMObjectFromClassName("CIMMarkerGraphic", "V3")
    # A triangle pointing along the line.
    graphic.geometry = {"rings": [[[5.0, 0.0], [-5.0, 4.0], [-5.0, -4.0], [5.0, 0.0]]]}
    fill = _fill_symbol(common.ARROW_COLOR)
    fill.symbolLayers = [
        _stroke(common.ARROW_EDGE_COLOR, common.ARROW_EDGE_PT)
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
        _stroke(common.ARROW_COLOR, common.ARROW_WIDTH_PT),
        _stroke(common.ARROW_EDGE_COLOR, common.ARROW_WIDTH_PT + 2 * common.ARROW_EDGE_PT),
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
