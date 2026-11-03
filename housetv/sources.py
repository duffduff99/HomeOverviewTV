"""Data sources: the real Home Assistant, or a built-in demo for trying things out."""
from __future__ import annotations

import asyncio
import logging
import math
import random
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import aiohttp

from .energy import EnergyFetcher
from .ha import HAClient

if TYPE_CHECKING:
    from .hub import Hub

log = logging.getLogger(__name__)


class HASource:
    demo = False

    def __init__(self, url: str, token: str, session: aiohttp.ClientSession):
        self.url = url
        self.token = token
        self.session = session
        self.ha = HAClient(url, token, session)
        self.energy = EnergyFetcher(self.ha)
        self.hub: Hub | None = None

    async def start(self, hub: "Hub") -> None:
        self.hub = hub
        self.ha.on_connect.append(self._on_connect)
        asyncio.create_task(self.ha.run_forever())

    async def _on_connect(self) -> None:
        assert self.hub
        await self.ha.subscribe("subscribe_events", self._on_event, event_type="state_changed")
        states = await self.ha.call("get_states")
        self.hub.replace_states({s["entity_id"]: s for s in states})
        await self.energy.refresh_prefs()
        self.hub.on_source_ready()

    async def _on_event(self, event: dict) -> None:
        data = event.get("data", {})
        if self.hub and data.get("entity_id"):
            self.hub.update_state(data["entity_id"], data.get("new_state"), data.get("old_state"))

    @property
    def ready(self) -> bool:
        return self.ha.connected.is_set()

    @property
    def timezone(self) -> str | None:
        return self.ha.ha_config.get("time_zone")

    @property
    def power_entities(self) -> dict[str, str]:
        return self.energy.power_entities

    async def forecast(self, entity_id: str, kind: str) -> list[dict]:
        resp = await self.ha.service_response("weather", "get_forecasts", entity_id, {"type": kind})
        return (resp.get(entity_id) or {}).get("forecast") or []

    async def calendar(self, entity_ids: list[str], days: int) -> dict[str, list[dict]]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        resp = await self.ha.service_response(
            "calendar", "get_events", entity_ids,
            {"start_date_time": now.isoformat(),
             "end_date_time": (now + timedelta(days=days)).isoformat()})
        return {eid: (resp.get(eid) or {}).get("events") or [] for eid in entity_ids}

    async def energy_today(self) -> dict | None:
        return await self.energy.fetch_today()

    async def history(self, entity_id: str) -> list:
        return await self.energy.fetch_history(entity_id)

    async def camera_stream_url(self, entity_id: str) -> str | None:
        res = await self.ha.call("camera/stream", entity_id=entity_id, format="hls")
        return (res or {}).get("url")

    async def camera_snapshot(self, entity_id: str) -> tuple[bytes, str]:
        async with self.session.get(
            f"{self.url}/api/camera_proxy/{entity_id}",
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            resp.raise_for_status()
            return await resp.read(), resp.content_type


# --------------------------------------------------------------------------
# Demo source: realistic fake data so you can try the channel without HA.
# --------------------------------------------------------------------------

def _st(entity_id: str, state: Any, **attrs: Any) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {"entity_id": entity_id, "state": str(state), "attributes": attrs,
            "last_changed": now, "last_updated": now}


DEMO_TRACKS = [
    ("Harbor Lights", "The Night Shift"), ("Golden Hour", "Coastline"),
    ("Paper Lanterns", "Mira Vale"), ("Slow Tide", "Northern Avenue"),
]


class DemoSource:
    demo = True
    ready = True
    timezone = None

    def __init__(self) -> None:
        self.hub: Hub | None = None
        self.track = 0

    @property
    def power_entities(self) -> dict[str, str]:
        return {}

    async def start(self, hub: "Hub") -> None:
        self.hub = hub
        hub.replace_states(self._states())
        hub.on_source_ready()
        asyncio.create_task(self._tick())

    def _solar_w(self, t: datetime) -> float:
        hour = t.hour + t.minute / 60
        return max(0.0, math.sin((hour - 6.5) / 12.5 * math.pi)) * 11800

    def _states(self) -> dict[str, dict]:
        now = datetime.now()
        solar = round(self._solar_w(now) * random.uniform(0.92, 1.0))
        home = round(random.uniform(1400, 2600))
        battery = round(min(5000, max(-5000, home - solar)) if solar < home else -min(6000, solar - home))
        grid = home - solar - battery
        title, artist = DEMO_TRACKS[self.track % len(DEMO_TRACKS)]
        sun_up = 7 <= now.hour < 18
        s = [
            _st("sun.sun", "above_horizon" if sun_up else "below_horizon",
                next_rising=(now.replace(hour=7, minute=12) + timedelta(days=1)).astimezone().isoformat(),
                next_setting=now.replace(hour=17, minute=41).astimezone().isoformat()),
            _st("weather.home", "partlycloudy", temperature=58, humidity=64, wind_speed=8,
                temperature_unit="°F", wind_speed_unit="mph", friendly_name="Home"),
            _st("sensor.outdoor_temperature", round(random.uniform(57, 58.4), 1),
                unit_of_measurement="°F", friendly_name="Outdoor Temperature", device_class="temperature"),
            _st("sensor.outdoor_humidity", 64, unit_of_measurement="%", friendly_name="Outdoor Humidity"),
            _st("sensor.outdoor_aqi", 38, friendly_name="Air Quality Index"),
            _st("sensor.outdoor_pm25", 2.5, unit_of_measurement="µg/m³", friendly_name="PM2.5"),
            _st("sensor.outdoor_pm10", 4.3, unit_of_measurement="µg/m³", friendly_name="PM10"),
            _st("sensor.outdoor_pm1", 3.8, unit_of_measurement="µg/m³", friendly_name="PM1"),
            _st("sensor.outdoor_pm03", 382, unit_of_measurement="particles/dL", friendly_name="PM0.3"),
            _st("sensor.outdoor_voc", 78, friendly_name="VOC index"),
            _st("sensor.outdoor_nox", 1, friendly_name="NOx index"),
            _st("sensor.outdoor_co2", 408, unit_of_measurement="ppm", friendly_name="CO2"),
            _st("sensor.wind_speed", 8.4, unit_of_measurement="mph", friendly_name="Wind"),
            _st("sensor.rain_today", 0.12, unit_of_measurement="in", friendly_name="Rain Today"),
            _st("sensor.uv_index", 3, friendly_name="UV Index"),
            _st("sensor.pv_power", solar, unit_of_measurement="W", friendly_name="Solar Power"),
            _st("sensor.battery_power", battery, unit_of_measurement="W", friendly_name="Battery Power"),
            _st("sensor.battery_soc", 78, unit_of_measurement="%", friendly_name="Battery"),
            _st("sensor.grid_power", grid, unit_of_measurement="W", friendly_name="Grid Power"),
            _st("sensor.home_power", home, unit_of_measurement="W", friendly_name="Home Power"),
            _st("sensor.pv1_power", round(solar * 0.38), unit_of_measurement="W", friendly_name="String 1"),
            _st("sensor.pv2_power", round(solar * 0.34), unit_of_measurement="W", friendly_name="String 2"),
            _st("sensor.pv3_power", round(solar * 0.28), unit_of_measurement="W", friendly_name="String 3"),
            _st("media_player.house_fm", "playing", friendly_name="House FM",
                media_title=title, media_artist=artist),
            _st("media_player.kitchen", "idle", friendly_name="Kitchen Speaker"),
            _st("input_text.tv_message", "Welcome home! Dinner is at 6:30.", friendly_name="TV Message"),
            _st("binary_sensor.front_door_motion", "off", friendly_name="Front Door Motion"),
            _st("binary_sensor.weather_alert", "off", friendly_name="Weather Alert", title=""),
            _st("sensor.next_trash_day", "Thursday", friendly_name="Trash Pickup"),
            _st("sensor.garage_door", "Closed", friendly_name="Garage Door"),
            _st("sensor.ev_charge", 72, unit_of_measurement="%", friendly_name="Car Battery"),
            _st("sensor.indoor_temperature", 70.5, unit_of_measurement="°F", friendly_name="Inside"),
        ]
        for i, name in enumerate(["Front Yard", "Driveway", "Back Yard", "Side Gate"], 1):
            s.append(_st(f"camera.camera_{i}", "idle", friendly_name=name))
        return {x["entity_id"]: x for x in s}

    async def _tick(self) -> None:
        n = 0
        while True:
            await asyncio.sleep(5)
            n += 1
            assert self.hub
            if n % 36 == 0:
                self.track += 1
            fresh = self._states()
            for eid in ("sensor.pv_power", "sensor.battery_power", "sensor.grid_power",
                        "sensor.home_power", "sensor.outdoor_temperature", "media_player.house_fm",
                        "sensor.pv1_power", "sensor.pv2_power", "sensor.pv3_power"):
                self.hub.update_state(eid, fresh[eid], None)

    async def forecast(self, entity_id: str, kind: str) -> list[dict]:
        today = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        conds = ["partlycloudy", "sunny", "rainy", "cloudy", "sunny", "snowy", "partlycloudy"]
        return [{"datetime": (today + timedelta(days=i)).astimezone().isoformat(),
                 "condition": conds[i % len(conds)], "temperature": 61 - i * 2 + (i % 2) * 3,
                 "templow": 44 - i, "precipitation_probability": [10, 0, 70, 30, 5, 60, 20][i % 7]}
                for i in range(7)]

    async def calendar(self, entity_ids: list[str], days: int) -> dict[str, list[dict]]:
        base = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
        events = [
            (2, 1, "Soccer practice"), (5, 2, "Dinner with the Parkers"),
            (26, 1, "Dentist"), (49, 0, "Trash & recycling"), (74, 3, "Movie night"),
        ]
        out = []
        for offset, length, title in events:
            start = base + timedelta(hours=offset)
            if length == 0:
                out.append({"summary": title, "start": start.date().isoformat(),
                            "end": (start.date() + timedelta(days=1)).isoformat()})
            else:
                out.append({"summary": title, "start": start.isoformat(),
                            "end": (start + timedelta(hours=length)).isoformat()})
        return {entity_ids[0]: out} if entity_ids else {}

    async def energy_today(self) -> dict | None:
        now = datetime.now()
        solar, home = [0.0] * 24, [0.0] * 24
        for h in range(now.hour + 1):
            frac = 1.0 if h < now.hour else now.minute / 60
            solar[h] = round(self._solar_w(now.replace(hour=h, minute=30)) / 1000 * frac, 2)
            home[h] = round((1.2 + 1.6 * math.exp(-((h - 18.5) ** 2) / 6) + 0.7 * math.exp(-((h - 7.5) ** 2) / 2)) * frac, 2)
        s, c = sum(solar), sum(home)
        exported = max(0.0, s - c - 8)
        imported = max(1.4, c - s * 0.9)
        return {"totals": {"solar": round(s, 1), "home": round(c, 1), "grid_in": round(imported, 1),
                           "grid_out": round(exported, 1), "battery_in": 9.6, "battery_out": 6.2,
                           "self_powered": round(100 * max(0, 1 - imported / c)) if c else None},
                "hourly": {"solar": solar, "home": home},
                "has": {"solar": True, "grid_in": True, "grid_out": True, "battery_in": True, "battery_out": True},
                "date": now.date().isoformat()}

    async def history(self, entity_id: str) -> list:
        now = datetime.now()
        pts, soc = [], 46.0
        for i in range(int((now.hour + now.minute / 60) * 4) + 1):
            h = i / 4
            sol = self._solar_w(now.replace(hour=int(h), minute=int((h % 1) * 60))) / 1000
            soc += (sol - 1.8) * 0.9 if sol > 1.8 else -0.35
            soc = min(100, max(12, soc))
            pts.append([h, round(soc, 1)])
        return pts

    async def camera_stream_url(self, entity_id: str) -> str | None:
        return None

    async def camera_snapshot(self, entity_id: str) -> tuple[bytes, str]:
        idx = entity_id[-1]
        hues = {"1": (198, 142), "2": (28, 210), "3": (140, 95), "4": (262, 180)}.get(idx, (200, 150))
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='960' height='540' viewBox='0 0 960 540'>
<defs><linearGradient id='g' x1='0' y1='0' x2='0' y2='1'>
<stop offset='0' stop-color='hsl({hues[0]},35%,62%)'/><stop offset='.55' stop-color='hsl({hues[0]},25%,40%)'/>
<stop offset='.56' stop-color='hsl({hues[1]},22%,30%)'/><stop offset='1' stop-color='hsl({hues[1]},20%,18%)'/></linearGradient></defs>
<rect width='960' height='540' fill='url(#g)'/>
<rect x='560' y='170' width='260' height='170' fill='rgba(0,0,0,.25)'/><polygon points='540,175 690,80 840,175' fill='rgba(0,0,0,.3)'/>
<rect x='120' y='260' width='30' height='90' fill='rgba(0,0,0,.35)'/><circle cx='135' cy='230' r='60' fill='rgba(20,60,30,.45)'/>
<text x='24' y='40' font-family='monospace' font-size='22' fill='white' opacity='.85'>DEMO CAM {idx}  {ts}</text></svg>"""
        return svg.encode(), "image/svg+xml"
