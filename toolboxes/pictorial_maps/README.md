# Pictorial Maps toolbox

Tools for pictorial maps: photos shown on the map, each joined to the place it
was taken by a leader line.

| Tool | What it does |
| ---- | ------------ |
| **Create Photo Callouts** | Takes the points from Geotagged Photos To Points, pulls out each photo, arranges the pictures around the edges of the map so they don't overlap and draws a leader line from each point to its picture. |
| **Style Photo Callouts** | Redraws the pictures on a callouts layer, for example to change their size. |

## How the line stays attached to the picture

Each callout is a single line feature. Its first vertex sits on the photo
point, and the picture is part of the line's symbol, drawn at the line's last
vertex. So the picture can't come apart from its line:

- **Move a picture:** select the callout, go to **Edit** > **Edit Vertices**,
  and drag the vertex in the middle of the picture. The line stretches to
  follow it.
- **Bend a leader line**, for example to go around something: add vertices to
  it in Edit Vertices. The picture always stays on the last vertex.
- Don't use the **Move** tool on a callout. It moves the whole line, including
  the end on the photo point.

## Workflow

1. Run **Geotagged Photos To Points** (Data Management Tools > Photos) on your
   folder of photos. Check **Add Photos As Attachments**: the photos are then
   copied into the geodatabase, so the callouts tool can still read them if
   the original files are moved or only online (for example in OneDrive).
2. Select the points you want callouts for. With a selection, only the
   selected points get callouts. A pictorial map reads best with around 5 to
   15 pictures; dozens of pictures fill the whole map.
3. Zoom the map (or the map frame in your layout) to show the area you want
   in the finished map. The pictures are placed inside what's shown.
4. Run **Create Photo Callouts** with the photo points layer as the input.
5. Drag pictures to tidy up the layout (see above).

### Parameters

- **Input Photo Points:** the output of Geotagged Photos To Points.
  Pictures come from the points' attachments, or from the file in the `Path`
  field when a point has no attachment.
- **Output Callouts:** the new line feature class. Upright, framed copies of
  the photos are saved in a folder next to its geodatabase, named
  `<output name>_images`.
- **Arrange Images:**
  - *Along the edges of the map* (default): pictures go around the inside
    edges of the map view (or the Picture Area), each as near its photo as
    possible, and leader lines don't cross. If the edges are full, more
    pictures go in rows further in. If they don't fit at all, the tool stops
    and says how many fit.
  - *Around the photos:* pictures go on a ring around the photo points, in
    the same order as the points, so leader lines don't cross. Many photos
    close together need a big ring, which can reach past the edge of the
    view; the tool warns when that happens.
  - *In a row above the photos:* pictures go in one row above the highest
    point, ordered west to east.
- **Image Height (points):** how tall each picture is on the page, at the
  reference scale. 72 points is one inch.
- **Reference Scale:** the map scale at which pictures are the height above.
  The tool sets the map's reference scale to it, so pictures grow and shrink
  with the map and keep their places when you zoom. Leave it blank to keep
  the map's current reference scale or, if it doesn't have one, to use the
  current view scale. To turn the reference scale off later: map
  **Properties** > **General** > **Reference scale** > *None*.
- **Picture Area:** for *Along the edges of the map*, the area to keep the
  pictures inside. Leave it blank to use what the active map view shows,
  or, in a layout, what the map frame shows.

### Output fields

| Field | Contents |
| ----- | -------- |
| `PhotoOID` | Object ID of the photo point the callout belongs to |
| `PhotoName` | Photo file name (the `Name` field of the photo points) |
| `PhotoPath` | Original photo file path (the `Path` field) |
| `PhotoTime` | When the photo was taken (the `DateTime` field) |
| `Direction` | Compass direction the camera faced (the `Direction` field) |
| `ImageFile` | The upright, framed copy of the photo used on the map |

## Notes

- If the map clips its layers to a shape (Map **Properties** > **Clip
  Layers**), pictures outside that shape would be cut off. The tool adds the
  callouts layer to the map's **Exclude layers from clipping** list so they
  still show.
- Phone photos are often saved sideways with a tag saying which way to turn
  them. ArcGIS picture symbols ignore that tag, so the tool turns the pictures
  upright itself.
- The pictures are embedded in the layer's symbology, so the project still
  shows them if the `_images` folder is moved. Style Photo Callouts reads
  the `ImageFile` paths again, so keep the folder if you want to restyle.
- Image Height and Reference Scale decide how much room each picture needs.
  If you change them a lot with Style Photo Callouts, the pictures may need
  rearranging. Run Create Photo Callouts again for a fresh layout.
- Pictures are drawn in the order of the features, so where a leader line
  passes another callout's picture, it can be drawn on top of it. Drag the
  picture a little to clear it.

## Tests

The layout and picture code is in `callout_layout.py`, which doesn't need
ArcGIS. Its tests run with any Python 3 that has Pillow:

```
python -m unittest discover -s toolboxes/pictorial_maps/tests
```
