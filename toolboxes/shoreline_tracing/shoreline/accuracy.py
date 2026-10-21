# -*- coding: utf-8 -*-
"""Score a traced line against the hand-drawn one. No arcpy here.

The toolbox puts a point every metre along the hand-drawn line and measures
how far each point is from the traced line. These functions turn those
distances into a short report.
"""

import math


def summarise(distances, within=(0.5, 1.0, 2.0)):
    """Summary of distances in metres, as a dict:
    count, mean, median, p90 (90 % of points are this close or closer),
    max, and within_<d> (share of points within d metres, 0 to 1).
    Points with no distance (None or NaN) are left out.
    """
    values = sorted(
        float(d) for d in distances
        if d is not None and not (isinstance(d, float) and math.isnan(d))
    )
    result = {"count": len(values)}
    if not values:
        return result
    result["mean"] = sum(values) / len(values)
    result["median"] = _percentile(values, 50)
    result["p90"] = _percentile(values, 90)
    result["max"] = values[-1]
    for limit in within:
        result[f"within_{limit:g}"] = sum(1 for v in values if v <= limit) / len(values)
    return result


def _percentile(sorted_values, percent):
    """Linear-interpolated percentile of an already sorted list."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * percent / 100.0
    low = int(math.floor(position))
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def report_line(name, summary):
    """One readable line for the tool messages."""
    if not summary.get("count"):
        return f"{name}: nothing to compare."
    shares = ", ".join(
        f"{share * 100:.0f}% within {key[len('within_'):]} m"
        for key, share in summary.items() if key.startswith("within_")
    )
    return (
        f"{name}: typical gap {summary['median']:.2f} m, average {summary['mean']:.2f} m, "
        f"90% of the line within {summary['p90']:.2f} m, worst {summary['max']:.1f} m "
        f"({shares}; {summary['count']} points)."
    )
