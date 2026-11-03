"""Pull today's energy totals from the Home Assistant Energy dashboard.

We ask HA which statistics the Energy dashboard uses (`energy/get_prefs`), then
read hourly + 5-minute long-term statistics for today. That means whatever you
configured in Settings -> Dashboards -> Energy shows up here with no extra setup.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .ha import HAClient

log = logging.getLogger(__name__)


def stats_from_prefs(prefs: dict) -> dict[str, list[str]]:
    """Map Energy dashboard prefs to lists of statistic ids per flow.

    Handles both the long-standing format (grid `flow_from`/`flow_to` lists) and
    flat `stat_energy_from`/`stat_energy_to` keys. Also collects any power
    (`stat_rate`) sensors newer HA versions let you attach.
    """
    out: dict[str, list[str]] = {k: [] for k in (
        "solar", "grid_in", "grid_out", "battery_in", "battery_out")}
    power: dict[str, str] = {}
    for src in prefs.get("energy_sources", []) or []:
        stype = src.get("type")
        if stype == "solar":
            _add(out["solar"], src.get("stat_energy_from"))
            _add_power(power, "solar", src)
        elif stype == "battery":
            _add(out["battery_out"], src.get("stat_energy_from"))  # discharged into the home
            _add(out["battery_in"], src.get("stat_energy_to"))      # charged
            _add_power(power, "battery", src)
        elif stype == "grid":
            for f in src.get("flow_from", []) or []:
                _add(out["grid_in"], f.get("stat_energy_from"))
            for f in src.get("flow_to", []) or []:
                _add(out["grid_out"], f.get("stat_energy_to"))
            _add(out["grid_in"], src.get("stat_energy_from"))
            _add(out["grid_out"], src.get("stat_energy_to"))
            _add_power(power, "grid", src)
    out["_power"] = power  # type: ignore[assignment]
    return out


def _add(lst: list, val: Any) -> None:
    if isinstance(val, str) and val and val not in lst:
        lst.append(val)


def _add_power(power: dict, key: str, src: dict) -> None:
    rate = src.get("stat_rate")
    if isinstance(rate, str) and rate:
        power.setdefault(key, rate)
    elif isinstance(rate, dict):  # some versions nest the sensor
        val = rate.get("stat_rate") or rate.get("entity_id")
        if isinstance(val, str):
            power.setdefault(key, val)


def _ts(value: Any) -> float:
    """Statistics `start` is ms since epoch (new) or an ISO string (old)."""
    if isinstance(value, (int, float)):
        return value / 1000 if value > 1e11 else float(value)
    return datetime.fromisoformat(str(value)).timestamp()


def summarise(stat_map: dict[str, list[str]], hourly: dict, five_min: dict,
              midnight: datetime) -> dict:
    """Combine statistics rows into today's totals and a 24-slot hourly series."""
    tz = midnight.tzinfo
    flows = [k for k in stat_map if not k.startswith("_")]
    buckets = {k: [0.0] * 24 for k in flows}
    seen_hours: dict[str, set[int]] = {k: set() for k in flows}

    def apply(rows_by_stat: dict, skip_seen: bool) -> None:
        for flow in flows:
            for sid in stat_map[flow]:
                for row in rows_by_stat.get(sid, []) or []:
                    change = row.get("change")
                    if change is None:
                        continue
                    hour = datetime.fromtimestamp(_ts(row["start"]), tz).hour
                    if skip_seen and hour in seen_hours[flow]:
                        continue
                    buckets[flow][hour] += float(change)
                    if not skip_seen:
                        seen_hours[flow].add(hour)

    apply(hourly, skip_seen=False)
    apply(five_min, skip_seen=True)  # fills the current, not-yet-compiled hour

    home = []
    for h in range(24):
        val = (buckets["solar"][h] + buckets["grid_in"][h] + buckets["battery_out"][h]
               - buckets["grid_out"][h] - buckets["battery_in"][h])
        home.append(max(val, 0.0))

    totals = {k: round(sum(v), 2) for k, v in buckets.items()}
    totals["home"] = round(sum(home), 2)
    used = totals["home"]
    from_grid = totals["grid_in"]
    totals["self_powered"] = round(100 * max(0.0, 1 - from_grid / used)) if used > 0 else None
    return {
        "totals": totals,
        "hourly": {
            "solar": [round(v, 3) for v in buckets["solar"]],
            "home": [round(v, 3) for v in home],
        },
        "has": {k: bool(stat_map[k]) for k in flows},
    }


class EnergyFetcher:
    def __init__(self, ha: HAClient):
        self.ha = ha
        self.stat_map: dict[str, list[str]] | None = None

    async def refresh_prefs(self) -> None:
        try:
            prefs = await self.ha.call("energy/get_prefs")
        except Exception as err:  # noqa: BLE001
            log.warning("Could not read Energy dashboard settings (%s). "
                        "Is the Energy dashboard configured?", err)
            self.stat_map = None
            return
        self.stat_map = stats_from_prefs(prefs or {})
        log.info("Energy dashboard statistics: %s",
                 {k: v for k, v in self.stat_map.items() if v})

    @property
    def power_entities(self) -> dict[str, str]:
        return dict((self.stat_map or {}).get("_power", {}))  # type: ignore[arg-type]

    async def fetch_today(self) -> dict | None:
        if self.stat_map is None:
            await self.refresh_prefs()
        if not self.stat_map:
            return None
        ids = sorted({sid for k, v in self.stat_map.items() if not k.startswith("_") for sid in v})
        if not ids:
            return None
        tz = ZoneInfo(self.ha.ha_config.get("time_zone") or "UTC")
        now = datetime.now(tz)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        common = {"statistic_ids": ids, "types": ["change"], "units": {"energy": "kWh"}}
        hourly = await self.ha.call(
            "recorder/statistics_during_period", start_time=midnight.isoformat(),
            end_time=(midnight + timedelta(days=1)).isoformat(), period="hour", **common)
        five = await self.ha.call(
            "recorder/statistics_during_period", start_time=hour_start.isoformat(),
            period="5minute", **common)
        data = summarise(self.stat_map, hourly or {}, five or {}, midnight)
        data["date"] = midnight.date().isoformat()
        return data

    async def fetch_history(self, entity_id: str, buckets: int = 96) -> list[list[float]]:
        """Today's history for one numeric entity, averaged into `buckets` slots."""
        tz = ZoneInfo(self.ha.ha_config.get("time_zone") or "UTC")
        midnight = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        res = await self.ha.call(
            "history/history_during_period", start_time=midnight.isoformat(),
            entity_ids=[entity_id], minimal_response=True, no_attributes=True,
            significant_changes_only=False)
        rows = (res or {}).get(entity_id, [])
        slot_len = 86400 / buckets
        sums = [0.0] * buckets
        counts = [0] * buckets
        start = midnight.timestamp()
        for row in rows:
            try:
                val = float(row.get("s"))
            except (TypeError, ValueError):
                continue
            ts = row.get("lu") or row.get("lc") or start
            idx = int((float(ts) - start) // slot_len)
            if 0 <= idx < buckets:
                sums[idx] += val
                counts[idx] += 1
        # carry forward so slow-changing sensors draw a continuous line
        now_idx = int((datetime.now(tz).timestamp() - start) // slot_len)
        out: list[list[float]] = []
        last = None
        for i in range(min(now_idx + 1, buckets)):
            if counts[i]:
                last = sums[i] / counts[i]
            if last is not None:
                out.append([i / buckets * 24, round(last, 2)])
        return out
