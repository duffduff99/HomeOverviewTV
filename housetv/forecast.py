"""Pick a forecast type the weather entity supports, and shape it for the screen.

Weather integrations differ: some offer daily forecasts, while others, such as
the US National Weather Service, only offer hourly and "twice daily" (separate
day and night periods). Asking for a type the entity doesn't support is an
error, so we check the entity's supported_features first.
"""
from __future__ import annotations

from typing import Any

FORECAST_DAILY = 1
FORECAST_HOURLY = 2
FORECAST_TWICE_DAILY = 4


def choose_type(requested: str, supported_features: Any) -> str:
    """Return the forecast type to request from Home Assistant."""
    try:
        feats = int(supported_features or 0)
    except (TypeError, ValueError):
        feats = 0
    if feats == 0:  # unknown: try what was asked for
        return requested
    if requested == "hourly":
        order = [(FORECAST_HOURLY, "hourly"), (FORECAST_DAILY, "daily"), (FORECAST_TWICE_DAILY, "twice_daily")]
    else:
        order = [(FORECAST_DAILY, "daily"), (FORECAST_TWICE_DAILY, "twice_daily"), (FORECAST_HOURLY, "hourly")]
    for flag, name in order:
        if feats & flag:
            return name
    return requested


def merge_twice_daily(rows: list[dict]) -> list[dict]:
    """Combine day/night periods into one entry per day (day high + night low).

    If the list starts with a night period (it's evening), that becomes a
    "Tonight" entry with only a low.
    """
    out: list[dict] = []
    for row in rows:
        if row.get("is_daytime", True):
            out.append({**row, "templow": row.get("templow"), "_has_night": False})
            continue
        night_temp = row.get("temperature")
        prev = out[-1] if out else None
        if prev is not None and prev.get("is_daytime", True) and not prev["_has_night"]:
            prev["templow"] = night_temp
            prev["_has_night"] = True
            p1, p2 = prev.get("precipitation_probability"), row.get("precipitation_probability")
            if p2 is not None and (p1 is None or p2 > p1):
                prev["precipitation_probability"] = p2
        elif not out:
            out.append({**row, "temperature": None, "templow": night_temp,
                        "label": "Tonight", "_has_night": True})
    for row in out:
        row.pop("_has_night", None)
    return out
