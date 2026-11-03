"""Minimal Home Assistant WebSocket client.

Only uses public, long-standing APIs (auth, get_states, subscribe_events,
call_service, recorder statistics/history, camera/stream) so HA upgrades are
unlikely to break it.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
from typing import Any, Awaitable, Callable

import aiohttp

log = logging.getLogger(__name__)

EventCallback = Callable[[dict], Awaitable[None] | None]


class HAError(Exception):
    pass


class HAClient:
    def __init__(self, url: str, token: str, session: aiohttp.ClientSession):
        self.url = url.rstrip("/")
        self.token = token
        self.session = session
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._subs: dict[int, EventCallback] = {}
        self.connected = asyncio.Event()
        self.on_connect: list[Callable[[], Awaitable[None]]] = []
        self.ha_config: dict = {}

    @property
    def ws_url(self) -> str:
        if self.url.startswith("https://"):
            return "wss://" + self.url[len("https://"):] + "/api/websocket"
        return "ws://" + self.url.removeprefix("http://") + "/api/websocket"

    async def run_forever(self) -> None:
        delay = 2
        while True:
            try:
                await self._run_once()
                delay = 2
            except asyncio.CancelledError:
                raise
            except HAError as err:
                log.error("Home Assistant: %s", err)
            except Exception as err:  # noqa: BLE001 - keep reconnecting no matter what
                log.warning("Home Assistant connection lost (%s); retrying in %ss", err, delay)
            self.connected.clear()
            self._fail_pending()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    def _fail_pending(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(HAError("disconnected"))
        self._pending.clear()
        self._subs.clear()

    async def _run_once(self) -> None:
        async with self.session.ws_connect(self.ws_url, heartbeat=30, max_msg_size=0) as ws:
            msg = await ws.receive_json()
            if msg.get("type") != "auth_required":
                raise HAError(f"unexpected greeting {msg}")
            await ws.send_json({"type": "auth", "access_token": self.token})
            msg = await ws.receive_json()
            if msg.get("type") != "auth_ok":
                raise HAError("authentication failed - check your long-lived access token")
            log.info("Connected to Home Assistant %s", msg.get("ha_version"))
            self._ws = ws
            reader = asyncio.create_task(self._reader(ws))
            try:
                self.ha_config = await self.call("get_config")
                self.connected.set()
                for cb in self.on_connect:
                    await cb()
                await reader
            finally:
                reader.cancel()
                self._ws = None

    async def _reader(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for raw in ws:
            if raw.type != aiohttp.WSMsgType.TEXT:
                continue
            data = raw.json()
            for msg in data if isinstance(data, list) else [data]:
                await self._dispatch(msg)
        raise ConnectionError("websocket closed")

    async def _dispatch(self, msg: dict) -> None:
        mid = msg.get("id")
        mtype = msg.get("type")
        if mtype == "result":
            fut = self._pending.pop(mid, None)
            if fut and not fut.done():
                if msg.get("success"):
                    fut.set_result(msg.get("result"))
                else:
                    err = msg.get("error") or {}
                    fut.set_exception(HAError(f"{err.get('code')}: {err.get('message')}"))
        elif mtype == "event":
            cb = self._subs.get(mid)
            if cb:
                try:
                    res = cb(msg.get("event", {}))
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:  # noqa: BLE001
                    log.exception("Error handling HA event")

    async def call(self, msg_type: str, timeout: float = 30, **kwargs: Any) -> Any:
        if self._ws is None:
            raise HAError("not connected")
        mid = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self._ws.send_json({"id": mid, "type": msg_type, **kwargs})
        return await asyncio.wait_for(fut, timeout)

    async def subscribe(self, msg_type: str, callback: EventCallback, **kwargs: Any) -> None:
        if self._ws is None:
            raise HAError("not connected")
        mid = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        self._subs[mid] = callback
        await self._ws.send_json({"id": mid, "type": msg_type, **kwargs})
        await asyncio.wait_for(fut, 30)

    async def service_response(self, domain: str, service: str, entity_id: str | list[str],
                               data: dict | None = None) -> dict:
        """Call a service that returns data (weather.get_forecasts, calendar.get_events)."""
        result = await self.call(
            "call_service", domain=domain, service=service,
            service_data=data or {}, target={"entity_id": entity_id},
            return_response=True,
        )
        return (result or {}).get("response") or {}
