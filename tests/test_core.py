from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from housetv import conditions
from housetv.config import load, normalise, watched_entities
from housetv.hub import Hub
from housetv.forecast import choose_type, merge_twice_daily
from housetv.energy import stats_from_prefs, summarise
from housetv.themes import scheduled_theme

ROOT = Path(__file__).resolve().parent.parent


def test_example_config_loads():
    cfg = load(ROOT / "config" / "config.example.yaml")
    types = [s["type"] for s in cfg["screens"]]
    assert "calendar" not in types  # disabled in the example
    assert types[:5] == ["weather", "energy", "indoor", "news", "cameras"]
    news_screen = cfg["screens"][3]
    assert [f["name"] for f in news_screen["feeds"]] == ["AP", "NPR", "BBC"]  # defaults
    assert [g["kind"] for g in cfg["screens"][0]["air_gauges"]] == ["pm25", "pm10", "pm1", "voc", "nox", "co2"]
    indoor = cfg["screens"][2]
    assert len(indoor["rooms"]) == 5 and indoor["erv"]["boost"] == "switch.erv_boost"
    ids = watched_entities(cfg)
    assert "sensor.pv_power" in ids and "sensor.outdoor_voc" in ids and "sun.sun" in ids
    assert "climate.thermostat" in ids and "sensor.erv_power" in ids and "sensor.kitchen_temperature" in ids


def test_unknown_screen_type_is_skipped_and_ids_unique():
    cfg = normalise({"screens": [{"type": "nope"}, {"type": "tiles", "id": "a"}, {"type": "tiles", "id": "a"}]})
    assert [s["id"] for s in cfg["screens"]] == ["a", "ax"]


def test_env_expansion(monkeypatch):
    monkeypatch.setenv("MQTT_HOST", "broker.lan")
    monkeypatch.delenv("MQTT_USERNAME", raising=False)
    cfg = normalise({})
    assert cfg["mqtt"]["host"] == "broker.lan"
    assert cfg["mqtt"]["username"] is None


def test_conditions():
    states = {
        "sun.sun": {"state": "above_horizon", "attributes": {}},
        "sensor.solar": {"state": "1200", "attributes": {"unit": "W"}},
        "binary_sensor.door": {"state": "off", "attributes": {}},
    }
    assert conditions.check_all([{"entity": "sun.sun", "state": "above_horizon"}], states)
    assert conditions.check_all({"entity": "sensor.solar", "above": 100, "below": 5000}, states)
    assert not conditions.check({"entity": "sensor.solar", "below": 100}, states)
    assert conditions.check({"entity": "binary_sensor.door", "not_state": ["on", "open"]}, states)
    assert not conditions.check({"entity": "missing.entity", "state": "x"}, states)
    assert not conditions.is_active({"entity": "binary_sensor.door"}, states)
    assert conditions.is_active({"entity": "sensor.solar"}, states)


def test_theme_schedule_wraps_year():
    sched = [{"theme": "holiday", "from": "12-01", "to": "01-05"}, {"theme": "autumn", "from": "09-22", "to": "11-30"}]
    assert scheduled_theme(sched, date(2026, 12, 25)) == "holiday"
    assert scheduled_theme(sched, date(2027, 1, 3)) == "holiday"
    assert scheduled_theme(sched, date(2026, 10, 1)) == "autumn"
    assert scheduled_theme(sched, date(2026, 7, 1)) is None


def test_energy_prefs_and_summary():
    prefs = {"energy_sources": [
        {"type": "grid", "flow_from": [{"stat_energy_from": "sensor.grid_in"}],
         "flow_to": [{"stat_energy_to": "sensor.grid_out"}]},
        {"type": "solar", "stat_energy_from": "sensor.pv", "stat_rate": "sensor.pv_w"},
        {"type": "battery", "stat_energy_from": "sensor.bat_out", "stat_energy_to": "sensor.bat_in"},
    ]}
    stat_map = stats_from_prefs(prefs)
    assert stat_map["solar"] == ["sensor.pv"]
    assert stat_map["grid_in"] == ["sensor.grid_in"] and stat_map["battery_in"] == ["sensor.bat_in"]
    assert stat_map["_power"] == {"solar": "sensor.pv_w"}

    tz = ZoneInfo("America/Chicago")
    midnight = datetime(2026, 6, 1, tzinfo=tz)
    ms = lambda h: int(midnight.replace(hour=h).timestamp() * 1000)  # noqa: E731
    hourly = {
        "sensor.pv": [{"start": ms(12), "change": 5.0}],
        "sensor.grid_in": [{"start": ms(0), "change": 1.0}],
        "sensor.grid_out": [{"start": ms(12), "change": 2.0}],
        "sensor.bat_in": [{"start": ms(12), "change": 1.0}],
        "sensor.bat_out": [{"start": ms(20), "change": 0.5}],
    }
    # current hour (13) comes from 5-minute stats; hour 12 must not be double counted
    five = {"sensor.pv": [{"start": ms(12), "change": 9.9}, {"start": ms(13), "change": 0.4}]}
    out = summarise(stat_map, hourly, five, midnight)
    assert out["hourly"]["solar"][12] == 5.0 and out["hourly"]["solar"][13] == 0.4
    assert out["hourly"]["home"][12] == 2.0      # 5 solar - 2 export - 1 charge
    assert out["totals"]["home"] == round(1.0 + 2.0 + 0.4 + 0.5, 2)
    assert out["totals"]["self_powered"] == round(100 * (1 - 1.0 / 3.9))


def test_interrupt_triggers():
    fake = type("H", (), {"states": {"sun.sun": {"state": "below_horizon", "attributes": {}}}})()
    fires = lambda item, new, old: Hub._interrupt_fires(fake, item, {"state": new}, old and {"state": old})  # noqa: E731
    on = {"entity": "binary_sensor.bell"}
    assert fires(on, "on", "off")
    assert not fires(on, "on", "on")          # no repeat while it stays on
    assert not fires(on, "off", "on")
    ev = {"entity": "event.bell", "to": "changed"}
    assert fires(ev, "2026-11-03T10:00:01", "2026-11-03T09:00:00")
    assert not fires(ev, "2026-11-03T10:00:01", "unavailable")   # HA restart
    assert not fires(ev, "2026-11-03T10:00:01", None)
    night_only = {**on, "when": [{"entity": "sun.sun", "state": "above_horizon"}]}
    assert not fires(night_only, "on", "off")


def test_forecast_type_choice():
    assert choose_type("daily", 6) == "twice_daily"   # NWS: hourly + twice daily
    assert choose_type("daily", 3) == "daily"
    assert choose_type("hourly", 4) == "twice_daily"
    assert choose_type("daily", None) == "daily"       # unknown: ask for what was configured


def test_merge_twice_daily():
    rows = [
        {"datetime": "d0n", "is_daytime": False, "temperature": 40, "condition": "clear-night"},
        {"datetime": "d1", "is_daytime": True, "temperature": 60, "precipitation_probability": 10},
        {"datetime": "d1n", "is_daytime": False, "temperature": 42, "precipitation_probability": 30},
        {"datetime": "d2", "is_daytime": True, "temperature": 58},
    ]
    out = merge_twice_daily(rows)
    assert [r["datetime"] for r in out] == ["d0n", "d1", "d2"]
    assert out[0]["label"] == "Tonight" and out[0]["temperature"] is None and out[0]["templow"] == 40
    assert out[1]["temperature"] == 60 and out[1]["templow"] == 42 and out[1]["precipitation_probability"] == 30
    assert out[2]["templow"] is None


def test_broadcast_defaults_and_overrides():
    cfg = normalise({"broadcast": {"min_dark": 52}})
    assert cfg["display"]["mode"] == "monitor"
    assert cfg["broadcast"]["min_dark"] == 52 and cfg["broadcast"]["body_size"] == 33
    assert cfg["broadcast"]["effects"] is True and cfg["broadcast"]["particle_density"] == 1.0
    assert cfg["broadcast"]["safe_area"] == 5
