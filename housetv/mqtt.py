"""MQTT bridge: makes the channel appear in Home Assistant as a device.

Uses MQTT discovery, so no custom integration is needed in Home Assistant.
Entities created (on a device named "<name> TV"): Theme, Screen, Next screen,
Background music, Music volume, Skip track, Background track, Message and
Default screen time.

Automations can also publish JSON to <topic>/show_camera:
  {"camera": "camera.front_door", "title": "Doorbell", "duration": 30}
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import aiomqtt

if TYPE_CHECKING:
    from .hub import Hub

log = logging.getLogger(__name__)


class MqttBridge:
    def __init__(self, hub: "Hub"):
        self.hub = hub
        self.client: aiomqtt.Client | None = None
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        hub.listeners.append(self.queue.put_nowait)

    @property
    def cfg(self) -> dict:
        return self.hub.cfg["mqtt"]

    @property
    def base(self) -> str:
        return self.cfg.get("topic", "house_tv").strip("/")

    async def run(self) -> None:
        delay = 2
        while True:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                log.warning("MQTT disconnected (%s); retrying in %ss", err, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def _run_once(self) -> None:
        will = aiomqtt.Will(f"{self.base}/status", "offline", retain=True)
        async with aiomqtt.Client(
            hostname=self.cfg["host"], port=int(self.cfg.get("port") or 1883),
            username=self.cfg.get("username") or None, password=self.cfg.get("password") or None,
            identifier=f"{self.base}-display", will=will,
        ) as client:
            self.client = client
            log.info("Connected to MQTT broker %s", self.cfg["host"])
            await client.subscribe(f"{self.base}/+/set")
            await client.subscribe(f"{self.base}/+/press")
            await client.subscribe(f"{self.base}/show_camera")
            await client.subscribe(f"{self.cfg.get('discovery_prefix', 'homeassistant')}/status")
            await self._publish_discovery()
            await client.publish(f"{self.base}/status", "online", retain=True)
            await self._publish_all()
            publisher = asyncio.create_task(self._publisher())
            try:
                async for msg in client.messages:
                    await self._handle(str(msg.topic), msg.payload.decode(errors="replace"))
            finally:
                publisher.cancel()
                self.client = None

    async def _publisher(self) -> None:
        while True:
            what = await self.queue.get()
            if what == "config":
                await self._publish_discovery()
            await self._publish_all()

    async def _pub(self, topic: str, payload: str | int) -> None:
        if self.client:
            await self.client.publish(f"{self.base}/{topic}", str(payload), retain=True)

    async def _publish_all(self) -> None:
        hub = self.hub
        await self._pub("theme/state", hub.overrides.get("theme") or "Auto")
        title = (hub.screen or {}).get("title") or (hub.screen or {}).get("id") or ""
        await self._pub("screen/state", title)
        await self._pub("music/state", "ON" if hub.music_enabled else "OFF")
        await self._pub("volume/state", hub.volume)
        await self._pub("duration/state", hub.default_duration)
        await self._pub("message/state", hub.overrides.get("message") or "")
        track = hub.track or {}
        label = " - ".join(x for x in (track.get("title"), track.get("artist")) if x)
        await self._pub("track/state", label or "Nothing")

    async def _publish_discovery(self) -> None:
        if not self.client:
            return
        prefix = self.cfg.get("discovery_prefix", "homeassistant")
        b = self.base
        device = {"identifiers": [b], "name": self.hub.cfg["name"] + " TV",
                  "manufacturer": "House TV", "model": "House Channel"}
        common = {"availability_topic": f"{b}/status", "device": device}
        screens = [s.get("title") or s["id"] for s in self.hub.cfg["screens"]] or ["-"]
        entities = {
            ("select", "theme"): {"name": "Theme", "icon": "mdi:palette",
                                  "options": ["Auto"] + sorted(self.hub.themes.themes),
                                  "state_topic": f"{b}/theme/state", "command_topic": f"{b}/theme/set"},
            ("select", "screen"): {"name": "Screen", "icon": "mdi:television-guide", "options": screens,
                                   "state_topic": f"{b}/screen/state", "command_topic": f"{b}/screen/set"},
            ("button", "next_screen"): {"name": "Next screen", "icon": "mdi:skip-next",
                                        "command_topic": f"{b}/next/press"},
            ("switch", "music"): {"name": "Background music", "icon": "mdi:music",
                                  "state_topic": f"{b}/music/state", "command_topic": f"{b}/music/set"},
            ("number", "volume"): {"name": "Music volume", "icon": "mdi:volume-high", "min": 0, "max": 100,
                                   "step": 1, "unit_of_measurement": "%", "mode": "slider",
                                   "state_topic": f"{b}/volume/state", "command_topic": f"{b}/volume/set"},
            ("button", "skip_track"): {"name": "Skip track", "icon": "mdi:skip-forward",
                                       "command_topic": f"{b}/skip/press"},
            ("sensor", "now_playing"): {"name": "Background track", "icon": "mdi:music-note",
                                        "state_topic": f"{b}/track/state"},
            ("text", "message"): {"name": "Message", "icon": "mdi:message-text", "max": 255,
                                  "state_topic": f"{b}/message/state", "command_topic": f"{b}/message/set"},
            ("number", "screen_duration"): {"name": "Default screen time", "icon": "mdi:timer-outline",
                                            "min": 3, "max": 300, "step": 1, "unit_of_measurement": "s",
                                            "mode": "box", "state_topic": f"{b}/duration/state",
                                            "command_topic": f"{b}/duration/set"},
        }
        for (component, key), conf in entities.items():
            payload = {**common, **conf, "unique_id": f"{b}_{key}"}
            await self.client.publish(f"{prefix}/{component}/{b}/{key}/config",
                                      json.dumps(payload), retain=True)

    async def _handle(self, topic: str, payload: str) -> None:
        hub = self.hub
        b = self.base
        prefix = self.cfg.get("discovery_prefix", "homeassistant")
        try:
            if topic == f"{prefix}/status":
                if payload == "online":  # HA restarted: re-announce ourselves
                    await self._publish_discovery()
                    await self._publish_all()
            elif topic == f"{b}/theme/set":
                hub.set_theme(payload)
            elif topic == f"{b}/screen/set":
                hub.goto_screen(payload)
            elif topic == f"{b}/next/press":
                hub.next_screen()
            elif topic == f"{b}/music/set":
                hub.set_music(payload.upper() in ("ON", "1", "TRUE"))
            elif topic == f"{b}/volume/set":
                hub.set_volume(float(payload))
            elif topic == f"{b}/skip/press":
                hub.skip_track()
            elif topic == f"{b}/message/set":
                hub.set_message(payload)
            elif topic == f"{b}/duration/set":
                hub.set_default_duration(float(payload))
            elif topic == f"{b}/show_camera":
                data = json.loads(payload) if payload.strip().startswith("{") else {"camera": payload}
                if data.get("camera") in (None, "", "none", "off"):
                    hub.clear_interrupt()
                else:
                    hub.show_camera(data.get("camera"), data.get("title"), data.get("duration", 30))
        except (ValueError, TypeError) as err:
            log.warning("Ignoring bad MQTT command on %s: %r (%s)", topic, payload, err)
