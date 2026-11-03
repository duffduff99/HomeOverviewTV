"""Tiny condition language used by `show_when`, `alerts` and `interrupts`.

A condition is a mapping such as:

    {entity: sun.sun, state: above_horizon}
    {entity: sensor.solar_power, above: 50}
    {entity: binary_sensor.front_motion, state: "on", for_less_than: 120}
    {entity: media_player.house_fm, not_state: [off, idle, unavailable]}

A list of conditions means *all* must match.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Mapping

from .config import as_list


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _seconds_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return time.time() - datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return None


def check(cond: Mapping[str, Any], states: Mapping[str, dict], default_entity: str | None = None) -> bool:
    entity = cond.get("entity") or default_entity
    st = states.get(entity) if entity else None
    if st is None:
        return False
    attr = cond.get("attribute")
    value = st.get("attributes", {}).get(attr) if attr else st.get("state")

    if "state" in cond:
        wanted = [str(v) for v in as_list(cond["state"])]
        if str(value) not in wanted:
            return False
    if "not_state" in cond:
        unwanted = [str(v) for v in as_list(cond["not_state"])]
        if str(value) in unwanted:
            return False
    if "above" in cond:
        num = _to_float(value)
        if num is None or num <= float(cond["above"]):
            return False
    if "below" in cond:
        num = _to_float(value)
        if num is None or num >= float(cond["below"]):
            return False
    if "changed_within" in cond:
        # True if the entity's state changed in the last N seconds.
        age = _seconds_since(st.get("last_changed"))
        if age is None or age > float(cond["changed_within"]):
            return False
    return True


def check_all(conds: Any, states: Mapping[str, dict], default_entity: str | None = None) -> bool:
    return all(check(c, states, default_entity) for c in as_list(conds) if isinstance(c, Mapping))


INACTIVE_STATES = {"off", "0", "unknown", "unavailable", "none", "", "idle", "standby", "false"}


def is_active(item: Mapping[str, Any], states: Mapping[str, dict]) -> bool:
    """For alerts: explicit `when:` conditions, otherwise "state looks active"."""
    if item.get("when"):
        return check_all(item["when"], states, item.get("entity"))
    st = states.get(item.get("entity"))
    if not st:
        return False
    return str(st.get("state", "")).lower() not in INACTIVE_STATES
