# -*- coding: utf-8 -*-
"""File names and folder helpers. No arcpy here, so the tests can run anywhere."""

import json
import os
import re

LOW_TIDE = "Low Tide Line"
HIGH_TIDE = "High Tide Line"
VEGETATION = "Vegetation Line"
LINE_NAMES = (LOW_TIDE, HIGH_TIDE, VEGETATION)

SETTINGS_FILE = "shoreline_settings.json"
DEFAULT_CELL_SIZE = 0.15


def safe_name(text):
    """A folder name made from text: letters, digits and underscores only."""
    base = re.split(r"[\\/]", str(text))[-1]
    name = re.sub(r"[^A-Za-z0-9]+", "_", os.path.splitext(base)[0])
    return name.strip("_") or "survey"


def unique_names(paths):
    """A distinct safe_name for each path, adding _2, _3 ... to repeats."""
    seen = {}
    result = []
    for path in paths:
        base = safe_name(path)
        count = seen.get(base.lower(), 0) + 1
        seen[base.lower()] = count
        result.append(base if count == 1 else f"{base}_{count}")
    return result


def is_training_folder(folder):
    """Whether folder holds training tiles from Export Training Data For Deep
    Learning: an images folder and a labels folder side by side."""
    return (os.path.isdir(os.path.join(folder, "images"))
            and os.path.isdir(os.path.join(folder, "labels")))


def training_folders(folder):
    """The training-tile folders in folder: folder itself if it is one,
    otherwise each subfolder that is one, sorted by name."""
    if is_training_folder(folder):
        return [folder]
    if not os.path.isdir(folder):
        return []
    found = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if is_training_folder(path):
            found.append(path)
    return found


def write_settings(folder, settings):
    with open(os.path.join(folder, SETTINGS_FILE), "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)


def read_settings(folder):
    """Settings saved by Prepare Training Data, or {} when there are none."""
    path = os.path.join(folder, SETTINGS_FILE)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def find_line_file(folder, name):
    """Path of the shapefile or feature class called name in folder, or None.
    Matches 'Low Tide Line.shp', 'Low_Tide_Line.shp' and any capitalisation."""
    wanted = re.sub(r"[\s_]+", "", name).lower()
    if not os.path.isdir(folder):
        return None
    for entry in sorted(os.listdir(folder)):
        stem, ext = os.path.splitext(entry)
        if ext.lower() == ".shp" and re.sub(r"[\s_]+", "", stem).lower() == wanted:
            return os.path.join(folder, entry)
    return None
