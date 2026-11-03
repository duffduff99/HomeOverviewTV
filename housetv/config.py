"""Load and normalise config.yaml.

The YAML file is the single place users describe their channel. This module
fills in defaults so the rest of the code can assume every key exists.
Any string value may reference an environment variable as ${NAME}.
"""
from __future__ import annotations

import copy
import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

SCREEN_TYPES = {"weather", "energy", "cameras", "calendar", "tiles", "air"}

DEFAULTS: dict[str, Any] = {
    "name": "Our House",
    "subtitle": "House Channel",
    "homeassistant": {"url": "${HA_URL}", "token": "${HA_TOKEN}"},
    "display": {
        "safe_area": 3,          # % margin on every edge (TV overscan)
        "effects": True,         # animated seasonal particles
        "transition_seconds": 1, # crossfade length between screens
        "time_format": "12h",    # 12h | 24h
        "locale": "en-US",
    },
    "rotation": {"default_duration": 15},
    "theme": {"default": "night", "schedule": []},
    "header": {"temperature": None, "weather": None},
    "screens": [],
    "now_playing": {"media_players": []},
    "message": {"entity": None},
    "alerts": [],
    "interrupts": [],
    "music": {"enabled": True, "volume": 35, "shuffle": True, "duck_volume": 10},
    "mqtt": {
        "enabled": False,
        "host": "${MQTT_HOST}",
        "port": 1883,
        "username": "${MQTT_USERNAME}",
        "password": "${MQTT_PASSWORD}",
        "discovery_prefix": "homeassistant",
        "topic": "house_tv",
    },
}

SCREEN_DEFAULTS: dict[str, dict[str, Any]] = {
    "weather": {"title": "Outside", "forecast": "daily", "forecast_count": 5},
    "energy": {"title": "Energy", "use_energy_dashboard": True, "power": {}},
    "cameras": {"title": "Cameras", "mode": "live", "snapshot_interval": 3, "cameras": []},
    "calendar": {"title": "Calendar", "calendars": [], "days": 7, "max_events": 8},
    "tiles": {"title": "Around the House"},
    "air": {"title": "Air Quality", "gauges": []},
}

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        expanded = _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)
        # A value that was only "${VAR}" and VAR is unset becomes None.
        if expanded == "" and _ENV_RE.fullmatch(value):
            return None
        return expanded
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, val in (override or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], val)
        else:
            out[key] = val
    return out


def as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def normalise_entity_list(items: Any, key: str = "entity") -> list[dict]:
    """Accept `[sensor.a, {entity: sensor.b, name: B}]` and return dicts."""
    out = []
    for item in as_list(items):
        if isinstance(item, str):
            out.append({key: item})
        elif isinstance(item, dict) and item.get(key):
            out.append(dict(item))
    return out


def normalise(raw: dict) -> dict:
    cfg = _merge(DEFAULTS, raw or {})
    # Environment variables win over the file for secrets/connection details.
    if os.environ.get("HA_URL"):
        cfg["homeassistant"]["url"] = os.environ["HA_URL"]
    if os.environ.get("HA_TOKEN"):
        cfg["homeassistant"]["token"] = os.environ["HA_TOKEN"]
    cfg = _expand_env(cfg)
    if cfg["homeassistant"].get("url"):
        cfg["homeassistant"]["url"] = cfg["homeassistant"]["url"].rstrip("/")

    screens = []
    seen_ids: set[str] = set()
    for idx, screen in enumerate(as_list(cfg.get("screens"))):
        if not isinstance(screen, dict):
            continue
        stype = screen.get("type")
        if stype not in SCREEN_TYPES:
            log.warning("Ignoring screen %d: unknown type %r (expected one of %s)",
                        idx + 1, stype, ", ".join(sorted(SCREEN_TYPES)))
            continue
        if screen.get("enabled", True) is False:
            continue
        s = _merge(SCREEN_DEFAULTS[stype], screen)
        sid = str(s.get("id") or f"{stype}-{idx + 1}")
        while sid in seen_ids:
            sid += "x"
        seen_ids.add(sid)
        s["id"] = sid
        s["tiles"] = normalise_entity_list(s.get("tiles"))
        s["show_when"] = as_list(s.get("show_when"))
        if stype == "cameras":
            s["cameras"] = normalise_entity_list(s.get("cameras"))[:4]
        if stype == "weather":
            s["air_gauges"] = normalise_entity_list(s.get("air_gauges"))[:4]
        if stype == "air":
            s["gauges"] = normalise_entity_list(s.get("gauges"))[:6]
        if stype == "calendar":
            s["calendars"] = normalise_entity_list(s.get("calendars"))
        screens.append(s)
    cfg["screens"] = screens

    cfg["now_playing"]["media_players"] = normalise_entity_list(
        cfg["now_playing"].get("media_players"))
    cfg["alerts"] = normalise_entity_list(cfg.get("alerts"))
    cfg["interrupts"] = normalise_entity_list(cfg.get("interrupts"))
    cfg["theme"]["schedule"] = [s for s in as_list(cfg["theme"].get("schedule"))
                                if isinstance(s, dict) and s.get("theme")]
    return cfg


def load(path: Path) -> dict:
    if not path.exists():
        log.warning("No config file at %s - using defaults", path)
        return normalise({})
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return normalise(raw)


def watched_entities(cfg: dict) -> set[str]:
    """Every entity the display needs live state for."""
    ids: set[str] = set()

    def add(e):
        if isinstance(e, str) and "." in e:
            ids.add(e)

    for key in ("temperature", "weather"):
        add(cfg["header"].get(key))
    add(cfg["message"].get("entity"))
    for mp in cfg["now_playing"]["media_players"]:
        add(mp["entity"])
    for item in cfg["alerts"] + cfg["interrupts"]:
        add(item["entity"])
        for cond in as_list(item.get("when")):
            if isinstance(cond, dict):
                add(cond.get("entity"))
    for s in cfg["screens"]:
        for t in s["tiles"] + s.get("gauges", []) + s.get("air_gauges", []):
            add(t["entity"])
        for cond in s["show_when"]:
            if isinstance(cond, dict):
                add(cond.get("entity"))
        for key in ("weather", "temperature", "humidity", "air_quality", "wind",
                    "feels_like", "uv", "pressure", "rain", "pm25"):
            add(s.get(key))
        for val in (s.get("power") or {}).values():
            add(val)
        for cam in s.get("cameras", []):
            add(cam.get("motion"))
    add("sun.sun")
    return ids
