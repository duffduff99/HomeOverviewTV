from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from housetv import conditions
from housetv.config import load, normalise, watched_entities
from housetv.energy import stats_from_prefs, summarise
from housetv.themes import scheduled_theme

ROOT = Path(__file__).resolve().parent.parent


def test_example_config_loads():
    cfg = load(ROOT / "config" / "config.example.yaml")
    types = [s["type"] for s in cfg["screens"]]
    assert "calendar" not in types  # disabled in the example
    assert types[:3] == ["weather", "energy", "air"]
    ids = watched_entities(cfg)
    assert "sensor.pv_power" in ids and "sensor.outdoor_voc" in ids and "sun.sun" in ids


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
