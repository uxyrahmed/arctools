# -*- coding: utf-8 -*-
"""Short, readable messages about things that go wrong while the tools run.
No arcpy here, so the tests can run anywhere.
"""

import re

from . import surveys

LOCK_HINT = (
    "It may be open in another program or another ArcGIS Pro window, or "
    "OneDrive may be syncing it. Close it or let OneDrive finish, then run "
    "the tool again."
)

# What ArcGIS and Windows say when data is locked or in use.
_LOCK = re.compile(
    r"\block(s|ed|ing)?\b|ERROR 000464|ERROR 000601|being used by another process",
    re.IGNORECASE,
)
# ArcGIS tool errors start with a six-digit code, like 'ERROR 000732: ...'.
_ARCGIS_ERROR = re.compile(r"^\s*ERROR \d{6}", re.MULTILINE)


def is_lock_error(error):
    """Whether error says the data is locked or in use by something else."""
    return bool(_LOCK.search(str(error)))


def from_arcgis(error):
    """Whether error is an ArcGIS tool error, rather than a Python one."""
    return type(error).__name__ == "ExecuteError" or bool(_ARCGIS_ERROR.search(str(error)))


def error_text(error):
    """The useful part of error's message on one line, with a hint on what to
    do when the data is locked.

    ArcGIS adds 'Failed to execute (Delete).' lines that say nothing new, so
    they go. A Python error keeps its type, like 'AttributeError: ...', which
    helps when reporting it.
    """
    if isinstance(error, surveys.SurveyMapError):
        return str(error)
    lines = [line.strip() for line in str(error).splitlines()]
    text = " ".join(line for line in lines if line and not line.startswith("Failed to execute"))
    text = text or str(error).strip()
    if not from_arcgis(error):
        text = f"{type(error).__name__}: {text}" if text else type(error).__name__
    if is_lock_error(error):
        text += " " + LOCK_HINT
    return text


def problem(error, what=None, so=None):
    """A message for a step that failed: "Couldn't <what>, so <so>. <reason>".

    what says what the tool was doing, like "write SW_Points", and so says
    what happens instead, like "the layer is turned off". A SurveyMapError
    already says what went wrong, so its message is used as it is.
    """
    if isinstance(error, surveys.SurveyMapError) or not what:
        text = error_text(error)
        if so:
            text += f" {so[:1].upper()}{so[1:]}."
        return text
    consequence = f", so {so}" if so else ""
    return f"Couldn't {what}{consequence}. {error_text(error)}"


def needs_details(error):
    """Whether error looks like a bug in the tools rather than a problem with
    the data, so the Python details are worth showing."""
    return not (
        isinstance(error, surveys.SurveyMapError) or from_arcgis(error) or is_lock_error(error)
    )
