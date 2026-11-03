"""Run the real HA client against a fake Home Assistant WebSocket server."""
import asyncio

import aiohttp
from aiohttp import web

from housetv.ha import HAClient
from housetv.sources import HASource

STATES = [{"entity_id": "sensor.pv_power", "state": "1234", "attributes": {"unit_of_measurement": "W"},
           "last_changed": "2026-06-01T12:00:00+00:00"}]


async def fake_ha(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await ws.send_json({"type": "auth_required", "ha_version": "2026.10.0"})
    auth = await ws.receive_json()
    if auth.get("access_token") != "good":
        await ws.send_json({"type": "auth_invalid"})
        await ws.close()
        return ws
    await ws.send_json({"type": "auth_ok", "ha_version": "2026.10.0"})
    async for msg in ws:
        data = msg.json()
        mid, mtype = data["id"], data["type"]
        result = None
        if mtype == "get_config":
            result = {"time_zone": "America/Chicago"}
        elif mtype == "get_states":
            result = STATES
        elif mtype == "subscribe_events":
            await ws.send_json({"id": mid, "type": "result", "success": True, "result": None})
            await ws.send_json({"id": mid, "type": "event", "event": {"data": {
                "entity_id": "sensor.pv_power",
                "new_state": {**STATES[0], "state": "2000"}, "old_state": STATES[0]}}})
            continue
        elif mtype == "energy/get_prefs":
            result = {"energy_sources": [{"type": "solar", "stat_energy_from": "sensor.pv_energy"}]}
        elif mtype == "call_service":
            assert data["return_response"] is True
            result = {"context": {}, "response": {"weather.home": {"forecast": [{"condition": "sunny"}]}}}
        elif mtype == "unknown/thing":
            await ws.send_json({"id": mid, "type": "result", "success": False,
                                "error": {"code": "unknown_command", "message": "Unknown command."}})
            continue
        await ws.send_json({"id": mid, "type": "result", "success": True, "result": result})
    return ws


class FakeHub:
    def __init__(self):
        self.states = {}
        self.ready = asyncio.Event()
        self.updates = []

    def replace_states(self, states):
        self.states = states

    def update_state(self, entity_id, new, old):
        self.updates.append((entity_id, new["state"]))

    def on_source_ready(self):
        self.ready.set()


async def _run():
    app = web.Application()
    app.router.add_get("/api/websocket", fake_ha)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    async with aiohttp.ClientSession() as session:
        source = HASource(url, "good", session)
        hub = FakeHub()
        await source.start(hub)
        await asyncio.wait_for(hub.ready.wait(), 5)
        assert hub.states["sensor.pv_power"]["state"] == "1234"
        await asyncio.sleep(0.1)
        assert ("sensor.pv_power", "2000") in hub.updates
        assert source.timezone == "America/Chicago"
        assert source.energy.stat_map["solar"] == ["sensor.pv_energy"]
        assert await source.forecast("weather.home", "daily") == [{"condition": "sunny"}]
        try:
            await source.ha.call("unknown/thing")
            raise AssertionError("expected error")
        except Exception as err:  # noqa: BLE001
            assert "unknown_command" in str(err)

        bad = HAClient(url, "bad", session)
        task = asyncio.create_task(bad.run_forever())
        await asyncio.sleep(0.3)
        assert not bad.connected.is_set()
        task.cancel()
    await runner.cleanup()


def test_ha_client_against_fake_server():
    asyncio.run(_run())
