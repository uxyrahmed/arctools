# -*- coding: utf-8 -*-
"""Tools for making pictorial maps in ArcGIS Pro.

See README.md in this folder for how to use them.
"""

import importlib
import os
import re
import sys

import arcpy

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import callout_layout  # noqa: E402

# ArcGIS Pro keeps imported modules loaded between runs. Reload so edits to
# callout_layout.py are picked up when the toolbox is refreshed.
importlib.reload(callout_layout)

ARRANGEMENT_LABELS = {
    "Along the edges of the map": callout_layout.EDGES,
    "Around the photos": callout_layout.AROUND,
    "In a row above the photos": callout_layout.ROW_ABOVE,
}

# Fields written to the callouts feature class.
F_PHOTO_OID = "PhotoOID"
F_NAME = "PhotoName"
F_PATH = "PhotoPath"
F_TIME = "PhotoTime"
F_DIRECTION = "Direction"
F_IMAGE = "ImageFile"


class Toolbox:
    def __init__(self):
        self.label = "Pictorial Maps"
        self.alias = "pictorial"
        self.tools = [CreatePhotoCallouts, StylePhotoCallouts]


# ---------------------------------------------------------------------------
# Shared parameter helpers
# ---------------------------------------------------------------------------


def _image_height_parameter(name="image_height"):
    param = arcpy.Parameter(
        displayName="Image Height (points)",
        name=name,
        datatype="GPDouble",
        parameterType="Required",
        direction="Input",
    )
    param.value = 90
    return param


def _reference_scale_parameter(name="reference_scale"):
    return arcpy.Parameter(
        displayName="Reference Scale",
        name=name,
        datatype="GPDouble",
        parameterType="Optional",
        direction="Input",
    )


def _check_positive(param, what):
    if param.value is not None and param.value <= 0:
        param.setErrorMessage("{} must be greater than zero.".format(what))


# ---------------------------------------------------------------------------
# Tool: Create Photo Callouts
# ---------------------------------------------------------------------------


class CreatePhotoCallouts:
    def __init__(self):
        self.label = "Create Photo Callouts"
        self.description = (
            "Shows the photo of each point from Geotagged Photos To Points as "
            "a picture on the map, joined to its point by a leader line. "
            "Each callout is one line feature: it starts at the photo point "
            "and the picture is drawn at its other end, so moving that end "
            "moves the picture and the line stays attached.")
        self.category = None

    def getParameterInfo(self):
        in_photos = arcpy.Parameter(
            displayName="Input Photo Points",
            name="in_photos",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        in_photos.filter.list = ["Point"]

        out_callouts = arcpy.Parameter(
            displayName="Output Callouts",
            name="out_callouts",
            datatype="DEFeatureClass",
            parameterType="Required",
            direction="Output",
        )

        arrangement = arcpy.Parameter(
            displayName="Arrange Images",
            name="arrangement",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
        )
        arrangement.filter.type = "ValueList"
        arrangement.filter.list = list(ARRANGEMENT_LABELS)
        arrangement.value = "Along the edges of the map"

        picture_area = arcpy.Parameter(
            displayName="Picture Area",
            name="picture_area",
            datatype="GPExtent",
            parameterType="Optional",
            direction="Input",
        )

        return [
            in_photos,
            out_callouts,
            arrangement,
            _image_height_parameter(),
            _reference_scale_parameter(),
            picture_area,
        ]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        in_photos, out_callouts = parameters[0], parameters[1]
        if in_photos.value and in_photos.altered and not out_callouts.altered:
            try:
                name = arcpy.Describe(in_photos.value).baseName
                workspace = arcpy.env.workspace or arcpy.env.scratchGDB
                out_callouts.value = os.path.join(
                    workspace, arcpy.ValidateTableName(name + "_Callouts",
                                                       workspace))
            except Exception:
                pass
        # The picture area only applies when pictures go along the edges.
        parameters[5].enabled = (
            ARRANGEMENT_LABELS.get(parameters[2].valueAsText) ==
            callout_layout.EDGES)
        return

    def updateMessages(self, parameters):
        _check_positive(parameters[3], "Image height")
        _check_positive(parameters[4], "Reference scale")
        return

    def execute(self, parameters, messages):
        in_photos = parameters[0].valueAsText
        out_callouts = parameters[1].valueAsText
        arrangement = ARRANGEMENT_LABELS.get(parameters[2].valueAsText,
                                             parameters[2].valueAsText)
        image_height_pt = parameters[3].value
        scale = _resolve_reference_scale(parameters[4].value)

        photos = _read_photo_points(in_photos)
        if not photos:
            arcpy.AddError("The input has no photo points with a location.")
            raise arcpy.ExecuteError

        sr = _choose_spatial_reference(in_photos, photos)
        _project_photos(in_photos, photos, sr)

        image_folder = _image_folder_for(out_callouts)
        os.makedirs(image_folder, exist_ok=True)
        arcpy.AddMessage("Saving pictures to {}".format(image_folder))
        photos = _extract_images(in_photos, photos, image_folder)
        if not photos:
            arcpy.AddError(
                "None of the photos could be read. Run Geotagged Photos To "
                "Points with Add Photos As Attachments checked, or make sure "
                "the files in the Path field are available on this computer.")
            raise arcpy.ExecuteError
        arcpy.AddMessage("Making callouts for {} photos.".format(len(photos)))

        height = callout_layout.page_points_to_map_units(
            image_height_pt, scale, sr.metersPerUnit)
        anchors = [p["xy"] for p in photos]
        sizes = [(height * p["aspect"], height) for p in photos]
        extent = None
        if arrangement == callout_layout.EDGES:
            extent = _picture_area(parameters[5].value, sr)
        centres = callout_layout.arrange_images(
            anchors, sizes, arrangement, extent=extent)
        if extent is not None:
            _report_pictures_outside(extent, sizes, len(anchors))
        else:
            _warn_if_spread_out(anchors, centres, sr, scale, image_height_pt)

        _write_callouts(out_callouts, sr, photos, centres)
        arcpy.AddMessage(
            "Images are {:g} pt tall at 1:{:,.0f}. To move a picture, select "
            "its callout, open Edit Vertices and drag the vertex at the "
            "centre of the picture. If the pictures don't show, run Style "
            "Photo Callouts on the new layer.".format(image_height_pt, scale))
        return

    def postExecute(self, parameters):
        """Style the output layer once ArcGIS Pro has added it to the map."""
        _style_output(parameters[1].valueAsText, parameters[3].value,
                      parameters[4].value)
        return


# ---------------------------------------------------------------------------
# Tool: Style Photo Callouts
# ---------------------------------------------------------------------------


class StylePhotoCallouts:
    def __init__(self):
        self.label = "Style Photo Callouts"
        self.description = (
            "Draws the pictures on a callouts layer made by Create Photo "
            "Callouts. Use it to change the picture size, or if the layer was "
            "added to a map without its pictures.")
        self.category = None

    def getParameterInfo(self):
        in_callouts = arcpy.Parameter(
            displayName="Callouts Layer",
            name="in_callouts",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input",
        )
        in_callouts.filter.list = ["Polyline"]

        out_callouts = arcpy.Parameter(
            displayName="Updated Callouts Layer",
            name="out_callouts",
            datatype="GPFeatureLayer",
            parameterType="Derived",
            direction="Output",
        )
        out_callouts.parameterDependencies = [in_callouts.name]

        return [
            in_callouts,
            _image_height_parameter(),
            _reference_scale_parameter(),
            out_callouts,
        ]

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        return

    def updateMessages(self, parameters):
        _check_positive(parameters[1], "Image height")
        _check_positive(parameters[2], "Reference scale")
        return

    def execute(self, parameters, messages):
        layer = _find_map_layer(parameters[0].valueAsText)
        if layer is None:
            arcpy.AddError("Run this tool from ArcGIS Pro with the callouts "
                           "layer in the active map.")
            raise arcpy.ExecuteError
        pictures = _read_pictures(layer.dataSource)
        if not pictures:
            arcpy.AddError(
                "None of the callouts' pictures were found. They are the "
                "files in the {} field; run Create Photo Callouts again if "
                "they were moved or deleted.".format(F_IMAGE))
            raise arcpy.ExecuteError
        arcpy.AddMessage("Found pictures for {} callouts. They are drawn when "
                         "the tool finishes.".format(len(pictures)))
        parameters[3].value = parameters[0].value
        return

    def postExecute(self, parameters):
        """Draw the pictures. This has to happen here, after ArcGIS Pro has
        put the tool's output layer back in the map: changes made in execute
        are replaced by Pro's copy of the layer when the tool finishes."""
        try:
            layer = _find_map_layer(parameters[0].valueAsText)
            if layer is not None:
                _apply_callout_symbology(layer, parameters[1].value,
                                         parameters[2].value)
        except Exception as error:
            arcpy.AddWarning("Could not draw the pictures: {}".format(error))
        return


def _picture_area(requested, sr):
    """The (xmin, ymin, xmax, ymax) to keep pictures inside, in `sr`: the
    Picture Area parameter, else what the map view or map frame shows."""
    extent = requested
    if extent is None:
        camera = _active_map_and_camera()[1]
        if camera is not None:
            extent = camera.getExtent()
    if extent is None:
        arcpy.AddError("Set a Picture Area. There is no active map view or "
                       "layout to take one from.")
        raise arcpy.ExecuteError
    extent_sr = extent.spatialReference
    if extent_sr is not None and extent_sr.name and extent_sr.name != sr.name:
        extent = extent.projectAs(sr)
    return (extent.XMin, extent.YMin, extent.XMax, extent.YMax)


def _report_pictures_outside(extent, sizes, count):
    room = callout_layout.inside_edge_room(extent, sizes)
    if count > room:
        arcpy.AddMessage(
            "{} of the {} pictures fit along the inside edges of the map. "
            "The other {} are in rows just outside it: zoom out to see "
            "them.".format(room, count, count - room))


# Leader lines longer than this on the page usually mean the pictures ended
# up outside the area being mapped.
LONG_LEADER_INCHES = 4.0


def _warn_if_spread_out(anchors, centres, sr, scale, image_height_pt):
    """Pictures can't overlap, so many photos close together push them far
    out. Say so, rather than leave pictures off the edge of the view."""
    longest = callout_layout.longest_leader(anchors, centres)
    per_inch = callout_layout.page_points_to_map_units(
        callout_layout.POINTS_PER_INCH, scale, sr.metersPerUnit)
    inches = longest / per_inch
    metres = longest * sr.metersPerUnit
    arcpy.AddMessage("Longest leader line: {:,.0f} m ({:.1f} in on the "
                     "page).".format(metres, inches))
    if inches > LONG_LEADER_INCHES:
        arcpy.AddWarning(
            "{} pictures at {:g} pt don't fit near their photos, so some are "
            "{:,.0f} m away ({:.0f} in on the page at 1:{:,.0f}) and may be "
            "outside your view. For a readable map, select fewer photos "
            "(around 5 to 15) or lower the Image Height, then run the tool "
            "again.".format(len(anchors), image_height_pt, metres, inches,
                            scale))


# ---------------------------------------------------------------------------
# Reading the photo points
# ---------------------------------------------------------------------------


def _field_lookup(dataset):
    """Map upper-case field names to their real names."""
    return {f.name.upper(): f.name for f in arcpy.ListFields(dataset)}


def _read_photo_points(in_photos):
    """Read the photo points, honouring any selection on the layer."""
    desc = arcpy.Describe(in_photos)
    fields = _field_lookup(in_photos)
    extra = [fields.get(name.upper()) for name in
             ("Name", "Path", "DateTime", "Direction")]
    gid = desc.globalIDFieldName if getattr(desc, "hasGlobalID", False) else ""
    cursor_fields = ["OID@", "SHAPE@XY", gid or "OID@"] + [
        f or "OID@" for f in extra]

    photos = []
    skipped = 0
    with arcpy.da.SearchCursor(in_photos, cursor_fields) as cursor:
        for row in cursor:
            oid, xy, global_id = row[0], row[1], row[2]
            name, path, taken, direction = [
                value if field else None
                for value, field in zip(row[3:], extra)]
            if xy is None or None in xy:
                skipped += 1
                continue
            photos.append({
                "oid": oid,
                "global_id": global_id if gid else None,
                "lonlat": xy,
                "name": name or "Photo {}".format(oid),
                "path": path,
                "time": str(taken) if taken is not None else None,
                "direction": direction,
            })
    if skipped:
        arcpy.AddWarning("Skipped {} photos without a location.".format(
            skipped))
    return photos


def _choose_spatial_reference(in_photos, photos):
    """Pick a projected coordinate system so sizes and gaps are in metres
    or feet: the output coordinate system environment, then the map's, then
    the input's, then the UTM zone the photos are in."""
    candidates = [arcpy.env.outputCoordinateSystem]
    m = _current_map()
    if m is not None:
        candidates.append(m.spatialReference)
    in_sr = arcpy.Describe(in_photos).spatialReference
    candidates.append(in_sr)
    for sr in candidates:
        if sr is not None and sr.type == "Projected":
            return sr

    # The photos are in a geographic coordinate system (Geotagged Photos To
    # Points writes WGS 1984), so average their longitude and latitude.
    xs = [p["lonlat"][0] for p in photos]
    ys = [p["lonlat"][1] for p in photos]
    centre = arcpy.PointGeometry(
        arcpy.Point(sum(xs) / len(xs), sum(ys) / len(ys)), in_sr)
    lon_lat = centre.projectAs(arcpy.SpatialReference(4326)).firstPoint
    sr = arcpy.SpatialReference(callout_layout.utm_wkid(lon_lat.X,
                                                        lon_lat.Y))
    arcpy.AddMessage("Using {} for the callouts.".format(sr.name))
    return sr


def _project_photos(in_photos, photos, sr):
    """Add each photo's location in the output coordinate system."""
    by_oid = {p["oid"]: p for p in photos}
    with arcpy.da.SearchCursor(in_photos, ["OID@", "SHAPE@XY"],
                               spatial_reference=sr) as cursor:
        for oid, xy in cursor:
            if oid in by_oid:
                by_oid[oid]["xy"] = xy


# ---------------------------------------------------------------------------
# Pictures
# ---------------------------------------------------------------------------


def _image_folder_for(out_callouts):
    """A folder beside the output's geodatabase (or beside a shapefile)."""
    folder = os.path.dirname(out_callouts)
    name = os.path.splitext(os.path.basename(out_callouts))[0]
    walk = folder
    while walk:
        if os.path.splitext(walk)[1].lower() in (".gdb", ".sde", ".gpkg"):
            folder = os.path.dirname(walk)
            break
        parent = os.path.dirname(walk)
        if parent == walk:
            break
        walk = parent
    if not folder or not os.path.isdir(folder):
        folder = arcpy.env.scratchFolder
    return os.path.join(folder, name + "_images")


def _attachment_table(in_photos):
    path = arcpy.Describe(in_photos).catalogPath
    table = path + "__ATTACH"
    return table if arcpy.Exists(table) else None


def _read_attachments(table, photos):
    """Return {photo oid: image bytes} from an attachment table, using the
    first image attached to each photo."""
    fields = _field_lookup(table)
    if "REL_OBJECTID" in fields:
        key = fields["REL_OBJECTID"]
        wanted = {p["oid"]: p["oid"] for p in photos}
    elif "REL_GLOBALID" in fields:
        key = fields["REL_GLOBALID"]
        wanted = {p["global_id"]: p["oid"] for p in photos if p["global_id"]}
    else:
        return {}
    name_f = fields.get("ATT_NAME")
    type_f = fields.get("CONTENT_TYPE")
    data_f = fields.get("DATA")
    if not data_f:
        return {}

    found = {}
    keys = list(wanted)
    for start in range(0, len(keys), 500):
        chunk = keys[start:start + 500]
        values = ",".join(
            str(k) if isinstance(k, int) else "'{}'".format(k)
            for k in chunk)
        where = "{} IN ({})".format(arcpy.AddFieldDelimiters(table, key),
                                    values)
        cursor_fields = [key, data_f, name_f or key, type_f or key]
        with arcpy.da.SearchCursor(table, cursor_fields,
                                   where_clause=where) as cursor:
            for rel, data, name, content_type in cursor:
                oid = wanted.get(rel)
                if oid is None or oid in found or data is None:
                    continue
                if not callout_layout.is_image_attachment(
                        name if name_f else None,
                        content_type if type_f else None):
                    continue
                found[oid] = bytes(data)
    return found


def _extract_images(in_photos, photos, image_folder):
    """Save an upright thumbnail of each photo. Uses the photo attached to
    the point if there is one, otherwise the file in the Path field.
    Returns the photos that have a picture."""
    attached = {}
    table = _attachment_table(in_photos)
    if table:
        attached = _read_attachments(table, photos)
    arcpy.AddMessage("Found {} photos in attachments.".format(len(attached)))

    kept = []
    for photo in photos:
        source = attached.get(photo["oid"])
        if source is None and photo["path"] and os.path.isfile(photo["path"]):
            source = photo["path"]
        if source is None:
            arcpy.AddWarning("No picture found for {}.".format(photo["name"]))
            continue
        safe = re.sub(r"[^\w\-]+", "_", os.path.splitext(photo["name"])[0])
        out_path = os.path.join(image_folder,
                                "{}_{}.png".format(photo["oid"], safe))
        try:
            width, height = callout_layout.make_thumbnail(source, out_path)
        except Exception as error:
            arcpy.AddWarning("Could not read the picture for {}: {}".format(
                photo["name"], error))
            continue
        photo["image"] = out_path
        photo["aspect"] = width / float(height)
        kept.append(photo)
    return kept


# ---------------------------------------------------------------------------
# Writing the callouts
# ---------------------------------------------------------------------------


def _write_callouts(out_callouts, sr, photos, centres):
    out_path, out_name = os.path.split(out_callouts)
    arcpy.management.CreateFeatureclass(out_path, out_name, "POLYLINE",
                                        spatial_reference=sr)
    is_shapefile = arcpy.Describe(out_path).dataType == "Folder"
    long_text = 254 if is_shapefile else 1024
    arcpy.management.AddFields(out_callouts, [
        [F_PHOTO_OID, "LONG", "Photo OID"],
        [F_NAME, "TEXT", "Photo Name", 255],
        [F_PATH, "TEXT", "Photo Path", long_text],
        [F_TIME, "TEXT", "Date Taken", 50],
        [F_DIRECTION, "DOUBLE", "Direction"],
        [F_IMAGE, "TEXT", "Image File", long_text],
    ])

    fields = ["SHAPE@", F_PHOTO_OID, F_NAME, F_PATH, F_TIME, F_DIRECTION,
              F_IMAGE]
    with arcpy.da.InsertCursor(out_callouts, fields) as cursor:
        for photo, (x, y) in zip(photos, centres):
            ax, ay = photo["xy"]
            line = arcpy.Polyline(
                arcpy.Array([arcpy.Point(ax, ay), arcpy.Point(x, y)]), sr)
            cursor.insertRow([line, photo["oid"], photo["name"],
                              photo["path"], photo["time"],
                              photo["direction"], photo["image"]])


# ---------------------------------------------------------------------------
# Map and symbology
# ---------------------------------------------------------------------------


def _active_map_and_camera():
    """The map being worked on and the camera showing it: the active map
    view, or in an active layout the map frame showing the active map (or
    the first map frame). (None, None) outside ArcGIS Pro."""
    try:
        aprx = arcpy.mp.ArcGISProject("CURRENT")
    except Exception:
        return None, None
    m = aprx.activeMap
    view = aprx.activeView
    camera = getattr(view, "camera", None)
    if camera is not None:
        return m, camera
    if hasattr(view, "listElements"):
        for frame in view.listElements("MAPFRAME_ELEMENT"):
            if frame.map is None:
                continue
            if m is None or frame.map.name == m.name:
                return frame.map, frame.camera
    return m, None


def _current_map():
    return _active_map_and_camera()[0]


def _view_scale():
    camera = _active_map_and_camera()[1]
    return camera.scale if camera is not None else None


def _resolve_reference_scale(requested):
    """The scale at which images are drawn at their set height: the scale
    asked for, else the map's reference scale, else the current view scale."""
    if requested:
        return float(requested)
    m = _current_map()
    if m is not None and m.referenceScale:
        return float(m.referenceScale)
    scale = _view_scale()
    if scale:
        return float(scale)
    arcpy.AddError("Set a Reference Scale. There is no active map view to "
                   "take one from.")
    raise arcpy.ExecuteError


def _same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == \
        os.path.normcase(os.path.normpath(b))


def _map_layers_using(path):
    """Feature layers in the active map that draw a dataset."""
    m = _current_map()
    if m is None:
        return []
    return [layer for layer in m.listLayers()
            if layer.isFeatureLayer and layer.supports("DATASOURCE") and
            _same_path(layer.dataSource, path)]


def _find_map_layer(layer_or_path):
    """Find a layer in the active map by name or by data source."""
    m = _current_map()
    if m is None or not layer_or_path:
        return None
    for layer in m.listLayers():
        if layer.isFeatureLayer and layer_or_path in (layer.longName,
                                                      layer.name):
            return layer
    layers = _map_layers_using(layer_or_path)
    return layers[0] if layers else None


def _style_output(out_callouts, image_height_pt, requested_scale):
    """Called from postExecute. Problems here only produce a warning: the
    callouts were made and Style Photo Callouts can be run by hand."""
    try:
        m = _current_map()
        if m is None:
            return
        # Usually the layer ArcGIS Pro just added. If the tool overwrote an
        # earlier output, older layers drawing it are restyled too.
        layers = _map_layers_using(out_callouts)
        if not layers:
            layers = [m.addDataFromPath(out_callouts)]
        for layer in layers:
            _apply_callout_symbology(layer, image_height_pt, requested_scale)
    except Exception as error:
        arcpy.AddWarning(
            "The callouts were made but their pictures could not be drawn "
            "({}). Run Style Photo Callouts on the layer.".format(error))


def _read_pictures(data_source):
    """{photo OID as text: (photo name, picture file)} for the callouts
    whose picture file exists."""
    pictures = {}
    with arcpy.da.SearchCursor(data_source,
                               [F_PHOTO_OID, F_NAME, F_IMAGE]) as cursor:
        for oid, name, image in cursor:
            if image and os.path.isfile(image):
                pictures[_value_key(oid)] = (name, image)
    return pictures


def _apply_callout_symbology(layer, image_height_pt, requested_scale):
    """Give each callout a symbol with its picture at the end of the line,
    and make sure the map has a reference scale so the pictures keep their
    size relative to the map.

    Only call this from postExecute (or outside a tool): see
    StylePhotoCallouts.postExecute."""
    pictures = _read_pictures(layer.dataSource)

    # Change the map first. Setting the map's definition could reload its
    # layers, so the layer is looked up again before it is styled.
    m = _current_map()
    if m is not None:
        _set_reference_scale(m, requested_scale)
        uri = layer.getDefinition("V3").uRI
        if _exclude_from_clipping(m, uri):
            layer = _layer_with_uri(uri) or layer

    # Let ArcGIS Pro make the unique value classes from the values in the
    # data, so every callout is sure to match its class, then give each class
    # its picture.
    symbology = layer.symbology
    symbology.updateRenderer("UniqueValueRenderer")
    symbology.renderer.fields = [F_PHOTO_OID]
    layer.symbology = symbology

    definition = layer.getDefinition("V3")
    _add_pictures(definition.renderer, pictures, image_height_pt)
    layer.setDefinition(definition)
    _check_pictures_kept(layer, len(pictures))
    if m is not None:
        _hide_from_legends(m, layer)


def _set_reference_scale(m, requested_scale):
    scale = requested_scale or m.referenceScale or _view_scale()
    if scale and m.referenceScale != scale:
        m.referenceScale = scale
        arcpy.AddMessage(
            "Set the map's reference scale to 1:{:,.0f} so the pictures "
            "grow and shrink with the map.".format(scale))


def _hide_from_legends(m, layer):
    """Leave the callouts out of the legends of layouts that show this map:
    they are decoration, and every photo would otherwise be a legend entry.
    The layer stays on the map. To show it in a legend again, tick it under
    the legend in the layout's Contents pane."""
    try:
        layouts = set()
        for layout in arcpy.mp.ArcGISProject("CURRENT").listLayouts():
            for legend in layout.listElements("LEGEND_ELEMENT"):
                frame = legend.mapFrame
                if frame is None or frame.map is None or \
                        frame.map.name != m.name:
                    continue
                for item in list(legend.items):
                    if item.name != layer.name:
                        continue
                    if hasattr(item, "visible"):
                        item.visible = False
                    else:
                        legend.removeItem(item)
                    layouts.add(layout.name)
        if layouts:
            arcpy.AddMessage("Left the callouts out of the legend on "
                             "{}.".format(", ".join(sorted(layouts))))
    except Exception as error:
        arcpy.AddWarning(
            "To leave the callouts out of a legend, untick them under the "
            "legend in the layout's Contents pane ({}).".format(error))


def _layer_with_uri(uri):
    """The layer in the active map with this CIM URI."""
    m = _current_map()
    for layer in m.listLayers() if m is not None else []:
        try:
            if layer.isFeatureLayer and layer.getDefinition("V3").uRI == uri:
                return layer
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# CIM symbols
# ---------------------------------------------------------------------------


def _cim(class_name):
    return arcpy.cim.CreateCIMObjectFromClassName(class_name, "V3")


def _rgb(red, green, blue, alpha=100):
    color = _cim("CIMRGBColor")
    color.values = [red, green, blue, alpha]
    return color


def _stroke(width, color):
    stroke = _cim("CIMSolidStroke")
    stroke.enable = True
    stroke.width = width
    stroke.color = color
    stroke.capStyle = "Round"
    stroke.joinStyle = "Round"
    return stroke


def _leader_layers():
    """A white line with a dark edge, readable on imagery and on plain maps."""
    return [_stroke(1.5, _rgb(255, 255, 255)),
            _stroke(3.0, _rgb(40, 40, 40, 70))]


def _picture_layer(image_file, height_pt):
    """The photo, drawn upright at the last vertex of the line."""
    placement = _cim("CIMMarkerPlacementAtExtremities")
    placement.extremityPlacement = "JustEnd"
    placement.angleToLine = False

    picture = _cim("CIMPictureMarker")
    picture.enable = True
    picture.url = callout_layout.image_data_url(image_file)
    picture.size = height_pt
    # Width as a ratio of the picture's own proportions. Left unset it can be
    # zero, which draws nothing.
    picture.scaleX = 1.0
    picture.markerPlacement = placement
    return picture


def _symbol_reference(symbol_layers):
    symbol = _cim("CIMLineSymbol")
    # The first symbol layer is drawn on top.
    symbol.symbolLayers = symbol_layers
    reference = _cim("CIMSymbolReference")
    reference.symbol = symbol
    return reference


def _value_key(value):
    """A photo OID as text, the same whether it comes from the field or from
    a unique value class ("12", 12 and "12.0" all give "12")."""
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value)


def _add_pictures(renderer, pictures, image_height_pt):
    """Give each unique value class the picture of its photo. Callouts with
    no picture (for example drawn by hand) get a plain leader line."""
    for group in renderer.groups or []:
        group.heading = "Photo"
        for cls in group.classes or []:
            key = _value_key(cls.values[0].fieldValues[0]) if cls.values \
                else None
            picture = pictures.get(key)
            if picture is None:
                cls.symbol = _symbol_reference(_leader_layers())
                continue
            name, image_file = picture
            cls.label = name or key
            cls.symbol = _symbol_reference(
                [_picture_layer(image_file, image_height_pt)] +
                _leader_layers())
    renderer.defaultLabel = "Callouts without a picture"
    renderer.defaultSymbol = _symbol_reference(_leader_layers())
    renderer.useDefaultSymbol = True


def _check_pictures_kept(layer, expected):
    """Read the symbols back and say how many callouts have a picture, so a
    problem shows up in the tool messages rather than as empty lines."""
    try:
        renderer = layer.getDefinition("V3").renderer
        kept = 0
        for group in getattr(renderer, "groups", None) or []:
            for cls in group.classes or []:
                for symbol_layer in cls.symbol.symbol.symbolLayers or []:
                    url = getattr(symbol_layer, "url", None) or ""
                    if url.startswith("data:image"):
                        kept += 1
    except Exception as error:
        arcpy.AddWarning("Could not check the pictures: {}".format(error))
        return
    if kept == expected:
        arcpy.AddMessage("Pictures set on {} callouts.".format(kept))
    else:
        arcpy.AddWarning(
            "Pictures were set on {} callouts but only {} kept them. Please "
            "send these messages to whoever maintains this "
            "toolbox.".format(expected, kept))


def _exclude_from_clipping(m, uri):
    """Let the callouts layer draw past the map's clipping shape (Map
    Properties > Clip Layers), so pictures placed outside it still show.
    Returns True if the map was changed."""
    try:
        definition = m.getDefinition("V3")
        excluded = list(definition.layersExcludedFromClipping or [])
        if not uri or uri in excluded:
            return False
        definition.layersExcludedFromClipping = excluded + [uri]
        m.setDefinition(definition)
        return True
    except Exception as error:
        arcpy.AddWarning(
            "If the map clips its layers, exclude the callouts layer from "
            "clipping in Map Properties > Clip Layers ({}).".format(error))
        return False
