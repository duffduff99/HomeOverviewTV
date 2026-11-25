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

SCREEN_TYPES = {"weather", "energy", "cameras", "calendar", "tiles", "air", "indoor", "news"}
TYPE_ALIASES = {"agenda": "calendar", "tasks": "calendar", "todo": "calendar", "hvac": "indoor", "inside": "indoor",
                "headlines": "news"}

DEFAULTS: dict[str, Any] = {
    "name": "Our House",
    "subtitle": "House Channel",
    "homeassistant": {"url": "${HA_URL}", "token": "${HA_TOKEN}"},
    "display": {
        "safe_area": 3,          # % margin on every edge (TV overscan)
        "effects": True,         # animated seasonal particles
        "transition_seconds": 1, # crossfade length between screens
        "brightness": 1.0,       # picture adjustments, 1.0 = unchanged
        "contrast": 1.0,
        "saturation": 1.0,
        "levels": "full",        # full (PC, 0-255) or limited (video, 16-235)
        "high_contrast": False,  # brighter panels/borders/text for TVs via a modulator
        "tabs": "auto",          # auto, all, compact (current + next) or hidden
        "mode": "monitor",       # monitor, or broadcast (TV feed via a modulator); a display
                                 # can also choose with ?display=broadcast in its URL
        "time_format": "12h",    # 12h | 24h
        "locale": "en-US",
    },
    "rotation": {"default_duration": 15},
    # Broadcast mode (TV feed through a modulator). Sizes are design-canvas px
    # (1920x1080 layout; at 720p everything is 2/3 of this).
    "broadcast": {
        "min_dark": 45,          # 0-255: darkest level the background is lifted to (crush level)
        "panel_lift": 0.12,      # how much lighter panels are than the background (0-0.4)
        "panel_opacity": 0.72,   # 1 = solid panels; lower lets the background show through
        "panel_blur": 16,        # px of blur behind see-through panels (0 = none)
        "background_saturation": 0.85,  # tone down big saturated background areas
        "dither": 0.02,          # light noise over the background against banding (0 = off)
        "global_lift": 0.0,      # 0-0.2: also lift the darks of the whole picture (costs GPU)
        "red_gain": 1.0,         # e.g. 1.03 if whites still look slightly cyan
        "label_size": 20,        # small-label size (0 = same as on a monitor)
        "body_size": 28,         # body/value text size (0 = same as on a monitor)
        "line_width": 4,         # dividers, tracks, progress bars (keep even)
        "safe_area": 5,          # % margin on each side (TV overscan)
        "transition_seconds": 1,
        "animations": True,      # False: fades only and still energy-flow lines (calmer for the encoder)
        "effects": True,         # seasonal particles, same as on a monitor by default;
        "particle_density": 1.0, #   multipliers if they ever need taming on the TV
        "particle_size": 1.0,    #   (e.g. 0.5 density, 1.6 size, 0.5 speed)
        "particle_speed": 1.0,
    },
    "theme": {"default": "night", "schedule": []},
    "header": {"temperature": None, "weather": None},
    "screens": [],
    "now_playing": {"media_players": [], "show_up_next": True},
    "message": {
        "entity": None,
        "chime": True,           # play a chime when a message appears or changes
        "chime_volume": 60,      # 0-100
        "chime_sound": None,     # optional file in config/sounds/ instead of the built-in chime
    },
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
    "calendar": {"title": "Coming Up", "calendars": [], "todo_lists": [], "days": 7,
                 "max_events": 8, "max_tasks": 10},
    "tiles": {"title": "Around the House"},
    "air": {"title": "Air Quality", "gauges": []},
    "news": {"title": "Headlines", "max_headlines": 8, "max_age_hours": 24,
             "on_this_day": True, "on_this_day_count": 3, "language": "en"},
    "indoor": {"title": "Inside", "rooms": [], "erv": {}, "air_gauges": [],
               "duct_temps": [], "equipment_power": []},
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
        stype = TYPE_ALIASES.get(screen.get("type"), screen.get("type"))
        screen = {**screen, "type": stype}
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
        if stype in ("weather", "indoor"):
            s["air_gauges"] = normalise_entity_list(s.get("air_gauges"))[:6]
        if stype == "news":
            from .news import DEFAULT_FEEDS
            feeds = [f for f in as_list(s.get("feeds")) if isinstance(f, dict) and f.get("url")]
            s["feeds"] = feeds or [dict(f) for f in DEFAULT_FEEDS]
        if stype == "indoor":
            s["rooms"] = [r for r in as_list(s.get("rooms")) if isinstance(r, dict) and r.get("temperature")]
            s["erv"] = s.get("erv") if isinstance(s.get("erv"), dict) else {}
            s["duct_temps"] = normalise_entity_list(s.get("duct_temps"))
            s["equipment_power"] = normalise_entity_list(s.get("equipment_power"))
        if stype == "air":
            s["gauges"] = normalise_entity_list(s.get("gauges"))[:6]
        if stype == "calendar":
            s["calendars"] = normalise_entity_list(s.get("calendars"))
            s["todo_lists"] = normalise_entity_list(s.get("todo_lists"))
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
        for t in (s["tiles"] + s.get("gauges", []) + s.get("air_gauges", []) + s.get("todo_lists", [])
                  + s.get("duct_temps", []) + s.get("equipment_power", [])):
            add(t["entity"])
        for room in s.get("rooms", []):
            add(room.get("temperature"))
            add(room.get("humidity"))
        for key in ("mode", "status", "boost"):
            add((s.get("erv") or {}).get(key))
        for cond in s["show_when"]:
            if isinstance(cond, dict):
                add(cond.get("entity"))
        for key in ("weather", "temperature", "humidity", "air_quality", "wind",
                    "feels_like", "uv", "pressure", "rain", "pm25", "climate"):
            add(s.get(key))
        for val in (s.get("power") or {}).values():
            add(val)
        for cam in s.get("cameras", []):
            add(cam.get("motion"))
    add("sun.sun")
    return ids
