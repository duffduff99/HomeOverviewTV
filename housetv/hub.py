"""The channel controller.

Owns everything the TV shows: which screen is on, the theme, alerts, camera
pop-ups and music settings. Display pages (browsers) connect over a WebSocket
and simply render what the hub tells them. MQTT/Home Assistant controls call
the same methods.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import aiohttp
from aiohttp import web

from . import conditions, forecast, news
from .config import load, watched_entities
from .music import MusicLibrary
from .themes import Themes

log = logging.getLogger(__name__)

PERSIST_KEYS = ("theme", "music_enabled", "volume", "message", "default_duration")


class Hub:
    def __init__(self, config_path: Path, source: Any, themes: Themes, music: MusicLibrary):
        self.config_path = config_path
        self.state_path = config_path.parent / ".house-tv-state.json"
        self.source = source
        self.themes = themes
        self.music = music
        self.cfg: dict = load(config_path)
        self._cfg_mtime = self._mtime()
        self.watched = watched_entities(self.cfg)
        self.states: dict[str, dict] = {}
        self.clients: set[web.WebSocketResponse] = set()
        self.data: dict[str, Any] = {"forecast": {}, "calendar": {}, "todo": {}, "news": {},
                                     "energy": None, "history": {}}
        self._http: aiohttp.ClientSession | None = None  # for internet content (news)
        self.next_screen_id: str | None = None
        # Changes every time the server starts, so displays reload new page code after an update.
        self.version = uuid.uuid4().hex
        self._last_refresh: dict[str, float] = {}
        self.overrides: dict[str, Any] = self._load_overrides()
        self.screen_index = -1
        self.screen: dict | None = None
        self.screen_until = 0.0
        self._wake = asyncio.Event()
        self._goto: str | None = None
        self.interrupt: dict | None = None
        self._interrupt_task: asyncio.Task | None = None
        self.alerts: list[dict] = []
        self.track: dict | None = None
        self.theme: dict = {}
        self.listeners: list[Callable[[str], None]] = []  # MQTT bridge hooks
        self._refresh_now = asyncio.Event()

    # ------------------------------------------------------------------ setup
    def _mtime(self) -> float:
        try:
            return self.config_path.stat().st_mtime
        except OSError:
            return 0.0

    def _load_overrides(self) -> dict:
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {}

    def _save_overrides(self) -> None:
        try:
            self.state_path.write_text(json.dumps(self.overrides, indent=2))
        except OSError as err:
            log.debug("Could not persist runtime settings: %s", err)

    async def start(self) -> None:
        self.themes.scan()
        self.music.scan()
        self.theme = self.themes.resolve(self.cfg, self.overrides.get("theme"))
        await self.source.start(self)
        for coro in (self._rotation_loop(), self._refresh_loop(), self._housekeeping_loop()):
            asyncio.create_task(coro)

    def on_source_ready(self) -> None:
        self.request_refresh()

    # -------------------------------------------------------- derived values
    @property
    def music_enabled(self) -> bool:
        return bool(self.overrides.get("music_enabled", self.cfg["music"].get("enabled", True)))

    @property
    def volume(self) -> int:
        return int(self.overrides.get("volume", self.cfg["music"].get("volume", 35)))

    @property
    def default_duration(self) -> int:
        return int(self.overrides.get("default_duration", self.cfg["rotation"]["default_duration"]))

    @property
    def message(self) -> str:
        parts = []
        ent = self.cfg["message"].get("entity")
        st = self.states.get(ent) if ent else None
        if st and st.get("state") not in (None, "", "unknown", "unavailable"):
            parts.append(st["state"])
        if self.overrides.get("message"):
            parts.append(self.overrides["message"])
        return "  •  ".join(parts)

    def power_entities(self, screen: dict) -> dict:
        power = dict(self.source.power_entities)
        power.update({k: v for k, v in (screen.get("power") or {}).items() if v})
        return power

    def public_config(self) -> dict:
        screens = []
        for s in self.cfg["screens"]:
            s = dict(s)
            s.pop("show_when", None)
            if s["type"] == "energy":
                s["power"] = self.power_entities(s)
            screens.append(s)
        return {
            "name": self.cfg["name"],
            "subtitle": self.cfg["subtitle"],
            "display": self.cfg["display"],
            "broadcast": self.cfg["broadcast"],
            "header": self.cfg["header"],
            "screens": screens,
            "now_playing": self.cfg["now_playing"],
            "message": {k: v for k, v in self.cfg["message"].items() if k != "entity"},
            "timezone": self.source.timezone,
            "demo": self.source.demo,
        }

    def music_payload(self) -> dict:
        return {"enabled": self.music_enabled, "volume": self.volume,
                "duck_volume": self.cfg["music"].get("duck_volume", 10),
                "shuffle": self.cfg["music"].get("shuffle", True),
                "tracks": self.music.tracks}

    def screen_payload(self) -> dict:
        return {"id": self.screen["id"] if self.screen else None, "next": self.next_screen_id,
                "duration": self._duration(self.screen) if self.screen else 0,
                "remaining": max(0.0, self.screen_until - time.time())}

    def init_payload(self) -> dict:
        watched = {k: v for k, v in self.states.items() if k in self.watched or k.startswith("camera.")}
        return {"type": "init", "version": self.version, "config": self.public_config(), "theme": self.theme,
                "themes": sorted(self.themes.themes), "states": watched, "data": self.data,
                "screen": self.screen_payload(), "music": self.music_payload(),
                "alerts": self.alerts, "message": self.message, "interrupt": self.interrupt,
                "connected": self.source.ready}

    # ---------------------------------------------------------- broadcasting
    async def broadcast(self, msg: dict) -> None:
        if not self.clients:
            return
        text = json.dumps(msg, default=str)
        for ws in list(self.clients):
            try:
                await ws.send_str(text)
            except (ConnectionError, RuntimeError):
                self.clients.discard(ws)

    def _fire(self, msg: dict) -> None:
        asyncio.get_running_loop().create_task(self.broadcast(msg))

    def _notify(self, what: str) -> None:
        for cb in self.listeners:
            try:
                cb(what)
            except Exception:  # noqa: BLE001
                log.exception("listener failed")

    # ---------------------------------------------------------------- states
    @staticmethod
    def _clean(st: dict | None) -> dict | None:
        if not st:
            return st
        pic = (st.get("attributes") or {}).get("entity_picture")
        if isinstance(pic, str) and pic.startswith("/api/"):
            st = {**st, "attributes": {**st["attributes"], "entity_picture": "/ha" + pic}}
        return st

    def replace_states(self, states: dict[str, dict]) -> None:
        self.states = {k: self._clean(v) for k, v in states.items()}
        self._recompute_alerts()
        self._fire(self.init_payload())

    def update_state(self, entity_id: str, new: dict | None, old: dict | None) -> None:
        if new is None:
            self.states.pop(entity_id, None)
        else:
            self.states[entity_id] = self._clean(new)
        if entity_id not in self.watched and not entity_id.startswith("camera."):
            return
        self._fire({"type": "states", "states": {entity_id: self.states.get(entity_id)}})
        self._check_interrupts(entity_id, new, old)
        if entity_id.startswith("todo."):  # its state is the open-item count; refetch the items
            self.request_refresh([s["id"] for s in self.cfg["screens"]
                                  if any(t["entity"] == entity_id for t in s.get("todo_lists", []))])
        self._recompute_alerts()
        if entity_id == self.cfg["message"].get("entity"):
            self._fire({"type": "message", "message": self.message})
            self._notify("message")

    def _recompute_alerts(self) -> None:
        alerts = []
        for item in self.cfg["alerts"]:
            if conditions.is_active(item, self.states):
                st = self.states.get(item["entity"], {})
                attr = item.get("attribute")
                text = item.get("text") or (st.get("attributes", {}).get(attr) if attr else None) \
                    or st.get("attributes", {}).get("friendly_name") or item["entity"]
                alerts.append({"text": str(text), "level": item.get("level", "warning")})
        if alerts != self.alerts:
            self.alerts = alerts
            self._fire({"type": "alerts", "alerts": alerts})

    # -------------------------------------------------------------- rotation
    def _duration(self, screen: dict | None) -> int:
        if not screen:
            return self.default_duration
        return max(3, int(screen.get("duration") or self.default_duration))

    def _eligible(self) -> list[dict]:
        return [s for s in self.cfg["screens"] if conditions.check_all(s["show_when"], self.states)]

    async def _rotation_loop(self) -> None:
        while True:
            if self.interrupt:
                await self._wait(1)
                continue
            screens = self.cfg["screens"]
            if not screens:
                await self._wait(5)
                continue
            eligible = self._eligible() or screens[:1]
            current_id = self.screen["id"] if self.screen else None
            nxt = None
            if self._goto:
                nxt = next((s for s in screens if s["id"] == self._goto), None)
                self._goto = None
            if nxt is None:
                nxt = self._following(current_id, eligible)
            self.screen = nxt
            # What comes after this one, as things stand now (for "Next:" in the header).
            following = self._following(nxt["id"], eligible)
            self.next_screen_id = following["id"] if following and following["id"] != nxt["id"] else None
            dur = self._duration(nxt)
            self.screen_until = time.time() + dur
            await self.broadcast({"type": "screen", "screen": self.screen_payload()})
            self._notify("screen")
            await self._wait(dur)

    def _following(self, current_id: str | None, eligible: list[dict]) -> dict:
        """The next eligible screen after current_id, in configured order."""
        screens = self.cfg["screens"]
        ids = [s["id"] for s in screens]
        start = ids.index(current_id) + 1 if current_id in ids else 0
        ordered = screens[start:] + screens[:start]
        eligible_ids = {s["id"] for s in eligible}
        return next((s for s in ordered if s["id"] in eligible_ids), eligible[0])

    async def _wait(self, seconds: float) -> None:
        self._wake.clear()
        try:
            await asyncio.wait_for(self._wake.wait(), seconds)
        except asyncio.TimeoutError:
            pass

    def next_screen(self) -> None:
        self._wake.set()

    def goto_screen(self, key: str) -> bool:
        for s in self.cfg["screens"]:
            if key in (s["id"], s.get("title")):
                self._goto = s["id"]
                self._wake.set()
                return True
        return False

    # ------------------------------------------------------------ interrupts
    def _check_interrupts(self, entity_id: str, new: dict | None, old: dict | None) -> None:
        if not new:
            return
        for item in self.cfg["interrupts"]:
            if item["entity"] != entity_id:
                continue
            if self._interrupt_fires(item, new, old):
                self.show_camera(item.get("camera"), item.get("title"), item.get("duration", 30),
                                 item.get("position"))

    def _interrupt_fires(self, item: dict, new: dict, old: dict | None) -> bool:
        new_state = new.get("state")
        old_state = (old or {}).get("state")
        target = str(item.get("to", "on"))
        if target == "changed":
            # Event entities (e.g. event.front_doorbell) change their state to a new
            # timestamp on every press. Ignore the jump back from unavailable after
            # a Home Assistant restart.
            if old_state in (None, "unknown", "unavailable") or new_state in ("unknown", "unavailable"):
                return False
            fired = new_state != old_state
        else:
            fired = new_state == target and old_state != target
        return fired and conditions.check_all(item.get("when"), self.states)

    def show_camera(self, camera: str | None, title: str | None = None, duration: float = 30,
                    position: Any = None) -> None:
        duration = max(5, min(600, float(duration or 30)))
        if not camera:
            log.warning("show_camera called without a camera entity")
            return
        name = (self.states.get(camera, {}).get("attributes", {}) or {}).get("friendly_name", camera)
        self.interrupt = {"camera": camera, "title": title or name, "duration": duration,
                          "until": time.time() + duration, "position": position}
        self._fire({"type": "interrupt", "interrupt": self.interrupt})
        if self._interrupt_task:
            self._interrupt_task.cancel()
        self._interrupt_task = asyncio.get_running_loop().create_task(self._end_interrupt(duration))

    async def _end_interrupt(self, duration: float) -> None:
        await asyncio.sleep(duration)
        self.clear_interrupt()

    def clear_interrupt(self) -> None:
        if self.interrupt:
            self.interrupt = None
            self._fire({"type": "interrupt", "interrupt": None})
            self._wake.set()

    # ------------------------------------------------------ runtime controls
    def _set(self, key: str, value: Any) -> None:
        if value is None:
            self.overrides.pop(key, None)
        else:
            self.overrides[key] = value
        self._save_overrides()

    def set_theme(self, theme_id: str | None) -> None:
        self._set("theme", None if not theme_id or theme_id.lower() == "auto" else theme_id)
        self._apply_theme()

    def _apply_theme(self) -> None:
        theme = self.themes.resolve(self.cfg, self.overrides.get("theme"))
        if theme != self.theme:
            self.theme = theme
            self._fire({"type": "theme", "theme": theme})
        self._notify("theme")

    def set_music(self, enabled: bool) -> None:
        self._set("music_enabled", bool(enabled))
        self._fire({"type": "music", "music": self.music_payload()})
        self._notify("music")

    def set_volume(self, volume: float) -> None:
        self._set("volume", max(0, min(100, int(float(volume)))))
        self._fire({"type": "music", "music": self.music_payload()})
        self._notify("music")

    def skip_track(self) -> None:
        self._fire({"type": "music_cmd", "cmd": "skip"})

    def set_message(self, text: str) -> None:
        self._set("message", (text or "").strip() or None)
        self._fire({"type": "message", "message": self.message})
        self._notify("message")

    def set_default_duration(self, seconds: float) -> None:
        self._set("default_duration", max(3, int(float(seconds))))
        self._notify("duration")

    def set_track(self, track: dict | None) -> None:
        self.track = track
        self._notify("track")

    # ----------------------------------------------------- background loops
    def request_refresh(self, screen_ids: list[str] | None = None) -> None:
        """Refresh fetched data (forecast, calendar, tasks, energy) now instead of on schedule."""
        if screen_ids is None:
            self._last_refresh.clear()
        else:
            for sid in screen_ids:
                self._last_refresh.pop(sid, None)
        self._refresh_now.set()

    async def _refresh_loop(self) -> None:
        last = self._last_refresh
        while True:
            try:
                await asyncio.wait_for(self._refresh_now.wait(), 30)
            except asyncio.TimeoutError:
                pass
            self._refresh_now.clear()
            if not self.source.ready:
                continue
            now = time.time()
            for s in self.cfg["screens"]:
                try:
                    await self._refresh_screen(s, now, last)
                except Exception as err:  # noqa: BLE001
                    log.warning("Refreshing %s failed: %s", s["id"], err)

    async def _refresh_screen(self, s: dict, now: float, last: dict) -> None:
        key = s["id"]
        if s["type"] == "weather" and s.get("weather") and now - last.get(key, 0) > 900:
            requested = s.get("forecast", "daily")
            attrs = (self.states.get(s["weather"]) or {}).get("attributes") or {}
            kind = forecast.choose_type(requested, attrs.get("supported_features"))
            last[key] = now  # don't retry a failing forecast every 30 s
            fc = await self.source.forecast(s["weather"], kind)
            if kind == "twice_daily":
                fc = forecast.merge_twice_daily(fc)
            self.data["forecast"][key] = fc
            last[key] = now
            await self.broadcast({"type": "data", "key": "forecast", "id": key, "value": fc})
        elif s["type"] == "calendar" and now - last.get(key, 0) > 600:
            last[key] = now
            cal_ids = [c["entity"] for c in s["calendars"]]
            if cal_ids:
                events = await self.source.calendar(cal_ids, int(s.get("days", 7)))
                self.data["calendar"][key] = events
                await self.broadcast({"type": "data", "key": "calendar", "id": key, "value": events})
            todo_ids = [t["entity"] for t in s["todo_lists"]]
            if todo_ids:
                tasks = await self.source.todo(todo_ids)
                self.data["todo"][key] = tasks
                await self.broadcast({"type": "data", "key": "todo", "id": key, "value": tasks})
        elif s["type"] == "news" and now - last.get(key, 0) > 900:
            last[key] = now
            await self._refresh_news(s)
        elif s["type"] == "energy" and now - last.get(key, 0) > 240:
            last[key] = now
            if s.get("use_energy_dashboard", True):
                energy = await self.source.energy_today()
                self.data["energy"] = energy
                await self.broadcast({"type": "data", "key": "energy", "value": energy})
            soc = self.power_entities(s).get("battery_soc")
            if soc:
                hist = await self.source.history(soc)
                self.data["history"][soc] = hist
                await self.broadcast({"type": "data", "key": "history", "id": soc, "value": hist})

    async def _refresh_news(self, s: dict) -> None:
        key = s["id"]
        tz = ZoneInfo(self.source.timezone) if self.source.timezone else None
        today = datetime.now(tz).date()
        if self.source.demo:
            payload = {"headlines": news.demo_headlines(int(s["max_headlines"])),
                       "on_this_day": news.DEMO_ON_THIS_DAY[: int(s["on_this_day_count"])]
                       if s.get("on_this_day") else [], "date": today.isoformat()}
        else:
            if self._http is None:
                self._http = aiohttp.ClientSession()
            payload = dict(self.data["news"].get(key) or {})
            headlines = await news.fetch_headlines(self._http, s["feeds"], int(s["max_headlines"]),
                                                   float(s["max_age_hours"]))
            if headlines or "headlines" not in payload:  # keep the last good set if every feed failed
                payload["headlines"] = headlines
            if s.get("on_this_day") and payload.get("date") != today.isoformat():
                try:
                    payload["on_this_day"] = await news.fetch_on_this_day(
                        self._http, today, int(s["on_this_day_count"]), s.get("language", "en"))
                    payload["date"] = today.isoformat()
                except Exception as err:  # noqa: BLE001
                    log.warning("On this day failed: %s", err)
        self.data["news"][key] = payload
        await self.broadcast({"type": "data", "key": "news", "id": key, "value": payload})

    async def _housekeeping_loop(self) -> None:
        tick = 0
        today = date.today()
        while True:
            await asyncio.sleep(3)
            tick += 1
            mtime = self._mtime()
            if mtime != self._cfg_mtime:
                self._cfg_mtime = mtime
                await self.reload_config()
            if tick % 20 == 0:
                self.themes.scan()
                self._apply_theme()
                if date.today() != today:
                    today = date.today()
                    self.request_refresh()
                if self.music.scan():
                    await self.broadcast({"type": "music", "music": self.music_payload()})

    async def reload_config(self) -> None:
        try:
            cfg = load(self.config_path)
        except Exception as err:  # noqa: BLE001
            log.error("Config not reloaded - fix this error in %s: %s", self.config_path, err)
            return
        log.info("Configuration reloaded")
        self.cfg = cfg
        self.watched = watched_entities(cfg)
        self.theme = self.themes.resolve(cfg, self.overrides.get("theme"))
        self._recompute_alerts()
        self.request_refresh()
        await self.broadcast(self.init_payload())
        self._notify("config")
        self._wake.set()
