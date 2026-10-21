# -*- coding: utf-8 -*-
"""Reading a currents CSV and working out each current's speed and direction.
No arcpy here; arrows.py draws the arrows.

The CSV comes from the field device, one row per point:

    Name,Latitude,Longitude,UTM,Date Record
    C1 start,5.668124596,73.03368956,282219.358E 626887.752N 43N,15/10/2026 14:13
    C1 end,5.667565087,73.03367984,282218.071E 626825.871N 43N,15/10/2026 14:18

A current has a start point and an end point, named like 'C1 start' and
'C1 end'. Its speed is the distance between them over the time between them,
and its direction is the way it went, from start to end.
"""

import csv
import io
import math
import re
from collections import OrderedDict, namedtuple
from datetime import datetime, timezone

from . import directions, surveys

WGS84 = 4326

# Fields of the arrows feature class, after Name.
ARROW_FIELDS = (
    ("Label", "TEXT"),
    ("Speed_ms", "DOUBLE"),
    ("Bearing", "DOUBLE"),
    ("Direction", "TEXT"),
    ("Distance_m", "DOUBLE"),
    ("Minutes", "DOUBLE"),
    ("Start_Time", "DATE"),
    ("End_Time", "DATE"),
)

# One row of the CSV: where the point is (x, y in the coordinate system with
# this WKID) and when it was recorded.
Reading = namedtuple("Reading", "name x y wkid time")

# A current: its name ('C1') and its start and end readings.
Current = namedtuple("Current", "name start end")

_START_WORDS = ("START", "BEGIN", "BEGINNING")
_END_WORDS = ("END", "FINISH", "STOP")
_ROLE_AT_END = re.compile(r"^(.*?)[\s_\-]*(start|begin|end|finish|stop)$", re.IGNORECASE)

# Dates are read day first, as the field device writes them. A current's start
# and end are always read the same way, so the time between them is right
# either way.
_DATES = (
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%Y-%m-%d", "%Y/%m/%d",
    "%d-%b-%Y", "%d %b %Y", "%d-%b-%y", "%b %d %Y", "%m/%d/%Y",
)
_TIMES = (
    "%H:%M", "%H:%M:%S", "%H:%M:%S.%f", "%I:%M %p", "%I:%M:%S %p", "%I:%M%p", "%I:%M:%S%p",
)
_FORMATS = tuple(
    f"{date}{between}{time}" for date in _DATES for time in _TIMES for between in (" ", "T")
) + _TIMES

_UTM = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*m?\s*E\b[\s,;]*(-?\d+(?:\.\d+)?)\s*m?\s*N\b[\s,;]*(\d{1,2})\s*([A-Za-z])?"
)


# --- Reading the CSV ----------------------------------------------------------


def read_csv(path):
    """The readings in a currents CSV, and a list of problems with rows that
    were left out. Raises SurveyMapError if the file can't be used at all."""
    text = _read_text(path)
    rows = [row for row in csv.reader(io.StringIO(text), _dialect(text)) if any(c.strip() for c in row)]
    if not rows:
        raise surveys.SurveyMapError(f"The currents CSV is empty: {path}")
    columns = find_columns(rows[0])
    readings, problems = [], []
    for number, row in enumerate(rows[1:], start=2):
        reading, problem = read_row(row, columns, number)
        if reading is not None:
            readings.append(reading)
        else:
            problems.append(problem)
    if not readings:
        raise surveys.SurveyMapError(
            "None of the rows in the currents CSV could be read. "
            + (problems[0] if problems else "It has a header row but no points.")
        )
    return readings, problems


def _read_text(path):
    try:
        with open(str(path), "rb") as stream:
            data = stream.read()
    except OSError as error:
        raise surveys.SurveyMapError(f"Couldn't open the currents CSV. {error}") from error
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _dialect(text):
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        return csv.excel


def _key(header):
    return re.sub(r"[^a-z0-9]", "", str(header or "").casefold())


def find_columns(headers):
    """{'name', 'lat', 'lon', 'utm', 'date', 'time'} -> column index (or None)
    from the CSV's header row. Raises SurveyMapError when a column the tool
    needs isn't there."""
    keys = [_key(header) for header in headers]

    def first(test):
        return next((index for index, key in enumerate(keys) if test(key)), None)

    columns = {
        "name": _first_found(first(lambda k: k == "name"), first(lambda k: "name" in k)),
        "lat": first(lambda k: k.startswith("lat")),
        "lon": first(lambda k: k.startswith(("lon", "lng"))),
        "utm": first(lambda k: "utm" in k),
    }
    both = first(lambda k: "date" in k and "time" in k)
    if both is not None:
        columns["date"], columns["time"] = both, None
    else:
        columns["date"] = first(lambda k: "date" in k)
        columns["time"] = first(lambda k: "time" in k)

    found = ", ".join(str(header) for header in headers)
    if columns["name"] is None:
        raise surveys.SurveyMapError(
            f"The currents CSV needs a Name column. Its columns are: {found}"
        )
    if (columns["lat"] is None or columns["lon"] is None) and columns["utm"] is None:
        raise surveys.SurveyMapError(
            "The currents CSV needs Latitude and Longitude columns, or a UTM "
            f"column. Its columns are: {found}"
        )
    if columns["date"] is None and columns["time"] is None:
        raise surveys.SurveyMapError(
            "The currents CSV needs a column with the date and time each point "
            f"was recorded, such as 'Date Record'. Its columns are: {found}"
        )
    return columns


def _first_found(*indexes):
    return next((index for index in indexes if index is not None), None)


def _cell(row, index):
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def read_row(row, columns, number):
    """(Reading, None) for one CSV row, or (None, why it's left out)."""
    name = " ".join(_cell(row, columns["name"]).split())
    if not name:
        return None, f"Row {number} of the currents CSV has no name, so it's left out."
    position = _lat_lon(row, columns) or _utm(_cell(row, columns["utm"]))
    if position is None:
        return None, f"{name} has no position the tool can read, so it's left out."
    when_text = " ".join(
        part for part in (_cell(row, columns["date"]), _cell(row, columns["time"])) if part
    )
    when = parse_time(when_text)
    if when is None:
        shown = f"'{when_text}'" if when_text else "nothing"
        return None, f"{name} has {shown} for when it was recorded, which isn't a date and time the tool can read, so it's left out."
    x, y, wkid = position
    return Reading(name, x, y, wkid, when), None


def _number(text):
    text = text.strip()
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _lat_lon(row, columns):
    latitude = _number(_cell(row, columns["lat"]))
    longitude = _number(_cell(row, columns["lon"]))
    if latitude is None or longitude is None:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return longitude, latitude, WGS84


def _utm(text):
    """(easting, northing, WKID) from text like '282219.358E 626887.752N 43N'."""
    match = _UTM.search(text or "")
    if not match:
        return None
    zone = int(match.group(3))
    if not 1 <= zone <= 60:
        return None
    letter = (match.group(4) or "N").upper()
    # 'S' is south. Latitude band letters C to M are south of the equator too.
    south = letter == "S" or "C" <= letter <= "M"
    return float(match.group(1)), float(match.group(2)), (32700 if south else 32600) + zone


def parse_time(text):
    """A datetime from text like '15/10/2026 14:13', or None."""
    text = " ".join(str(text or "").split())
    if not text:
        return None
    for format_ in _FORMATS:
        try:
            return datetime.strptime(text, format_)
        except ValueError:
            continue
    try:
        when = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc).replace(tzinfo=None)
    return when


# --- Pairing start and end points -------------------------------------------


def only_currents(readings):
    """The readings of current points (names starting with C), and how many
    other points were left out, so a CSV of every survey point works too. If
    no name starts with C, all the readings."""
    prefixes = surveys.by_code(surveys.CURRENT_POINTS).prefixes
    kept = [reading for reading in readings if surveys.name_prefix(reading.name) in prefixes]
    if not kept:
        return list(readings), 0
    return kept, len(readings) - len(kept)


def split_name(name):
    """('C1', 'start') from 'C1 start', ('C1', 'end') from 'C1_END', and
    (name, None) when the name doesn't say start or end."""
    tokens = [token for token in re.split(r"[\s_\-]+", str(name).strip()) if token]
    for index, token in enumerate(tokens):
        role = "start" if token.upper() in _START_WORDS else "end" if token.upper() in _END_WORDS else None
        if role and len(tokens) > 1:
            return " ".join(tokens[:index] + tokens[index + 1:]), role
    match = _ROLE_AT_END.match(str(name).strip())
    if match and match.group(1):
        word = match.group(2).upper()
        return match.group(1), "start" if word in _START_WORDS else "end"
    return str(name).strip(), None


def pair_readings(readings):
    """The currents, each with its start and end reading, and a list of
    problems with points that couldn't be paired.

    A current's points share a name apart from 'start' and 'end'. Two points
    with the same name and no 'start' or 'end' in it are taken in the order
    they were recorded.
    """
    groups = OrderedDict()
    for reading in readings:
        name, role = split_name(reading.name)
        groups.setdefault(surveys.normalise(name), (name, []))[1].append((role, reading))

    found, problems = [], []
    for name, items in groups.values():
        starts = [reading for role, reading in items if role == "start"]
        ends = [reading for role, reading in items if role == "end"]
        if len(starts) == 1 and len(ends) == 1 and len(items) == 2:
            start, end = starts[0], ends[0]
        elif len(items) == 2 and not starts and not ends:
            start, end = sorted((reading for _, reading in items), key=lambda r: r.time)
        else:
            names = ", ".join(reading.name for _, reading in items)
            problems.append(
                f"{name} needs one start and one end point, but the CSV has: "
                f"{names}. It has no arrow."
            )
            continue
        if end.time <= start.time:
            problems.append(
                f"{name} ends at {_clock(end.time)}, which isn't after it starts "
                f"at {_clock(start.time)}, so its speed can't be worked out. It has no arrow."
            )
            continue
        found.append(Current(name, start, end))
    found.sort(key=lambda current: surveys.natural_key(current.name))
    return found, problems


def _clock(when):
    return when.strftime("%H:%M:%S") if when.second else when.strftime("%H:%M")


# --- Speed and direction ----------------------------------------------------


def seconds_between(current):
    return (current.end.time - current.start.time).total_seconds()


def label(speed_ms, bearing):
    """'0.21 m/s S': the speed and the way the current went. No direction
    when it didn't move."""
    text = f"{speed_ms:.{surveys.CURRENT_SPEED_DECIMALS}f} m/s"
    return text if bearing is None else f"{text} {directions.compass_point(bearing)}"


def measure(current, dx, dy):
    """Speed, bearing and the rest for a current that moved dx metres east and
    dy metres north: a dict with the arrow's fields, after Name."""
    distance = math.hypot(dx, dy)
    seconds = seconds_between(current)
    speed = distance / seconds
    bearing = directions.bearing_to(dx, dy) if distance > 0 else None
    return OrderedDict((
        ("Label", label(speed, bearing)),
        ("Speed_ms", round(speed, 4)),
        ("Bearing", round(bearing, 1) if bearing is not None else None),
        ("Direction", directions.compass_point(bearing) if bearing is not None else ""),
        ("Distance_m", round(distance, 2)),
        ("Minutes", round(seconds / 60.0, 2)),
        ("Start_Time", current.start.time),
        ("End_Time", current.end.time),
    ))


def describe(name, values):
    """'C1: 61.9 m in 5 min, 0.21 m/s S (bearing 181°)' for the tool's messages."""
    minutes = values["Minutes"]
    shown = f"{minutes:g} min" if minutes < 60 else f"{minutes / 60:.2g} h"
    bearing = values["Bearing"]
    towards = f" (bearing {bearing:.0f}\N{DEGREE SIGN})" if bearing is not None else ""
    return f"{name}: {values['Distance_m']:.1f} m in {shown}, {values['Label']}{towards}"
