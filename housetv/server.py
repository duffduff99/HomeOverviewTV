"""HTTP + WebSocket server for the display page."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import aiohttp
from aiohttp import web

from .hub import Hub

log = logging.getLogger(__name__)

# Only URLs that carry their own short-lived token are proxied, and no
# credentials are added, so this can't be used to reach the rest of HA.
PROXY_PREFIXES = ("api/hls/", "api/media_player_proxy/")
_SNAPSHOT_CACHE: dict[str, tuple[float, bytes, str]] = {}


def allowed_cameras(hub: Hub) -> set[str]:
    cams = {c["entity"] for s in hub.cfg["screens"] for c in s.get("cameras", [])}
    cams |= {i["camera"] for i in hub.cfg["interrupts"] if i.get("camera")}
    if hub.interrupt:
        cams.add(hub.interrupt["camera"])
    return cams


def build_app(hub: Hub, web_dir: Path, music_dir: Path, session: aiohttp.ClientSession) -> web.Application:
    app = web.Application()
    routes = web.RouteTableDef()
    ha_url = (hub.cfg["homeassistant"].get("url") or "").rstrip("/")

    @routes.get("/")
    async def index(_req: web.Request) -> web.StreamResponse:
        resp = web.FileResponse(web_dir / "index.html")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @routes.get("/health")
    async def health(_req: web.Request) -> web.Response:
        return web.json_response({"ok": True, "connected": hub.source.ready,
                                  "displays": len(hub.clients)})

    @routes.get("/ws")
    async def ws_handler(req: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(req)
        hub.clients.add(ws)
        log.info("Display connected (%d total)", len(hub.clients))
        try:
            await ws.send_str(json.dumps(hub.init_payload(), default=str))
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    continue
                if data.get("type") == "track":
                    hub.set_track(data.get("track"))
        finally:
            hub.clients.discard(ws)
            log.info("Display disconnected (%d left)", len(hub.clients))
        return ws

    @routes.get("/api/camera/{entity}/stream")
    async def camera_stream(req: web.Request) -> web.Response:
        entity = req.match_info["entity"]
        if entity not in allowed_cameras(hub):
            raise web.HTTPNotFound()
        try:
            url = await hub.source.camera_stream_url(entity)
        except Exception as err:  # noqa: BLE001
            log.warning("No live stream for %s (%s) - showing snapshots instead", entity, err)
            url = None
        return web.json_response({"url": ("/ha" + url) if url and url.startswith("/api/") else url})

    @routes.get("/api/camera/{entity}/snapshot")
    async def camera_snapshot(req: web.Request) -> web.Response:
        entity = req.match_info["entity"]
        if entity not in allowed_cameras(hub):
            raise web.HTTPNotFound()
        cached = _SNAPSHOT_CACHE.get(entity)
        if cached and time.time() - cached[0] < 1.5:  # several displays share one fetch
            return web.Response(body=cached[1], content_type=cached[2],
                                headers={"Cache-Control": "no-store"})
        try:
            body, ctype = await hub.source.camera_snapshot(entity)
        except Exception as err:  # noqa: BLE001
            log.debug("Snapshot for %s failed: %s", entity, err)
            raise web.HTTPServiceUnavailable() from err
        _SNAPSHOT_CACHE[entity] = (time.time(), body, ctype)
        return web.Response(body=body, content_type=ctype, headers={"Cache-Control": "no-store"})

    @routes.get("/ha/{path:.*}")
    async def ha_proxy(req: web.Request) -> web.StreamResponse:
        path = req.match_info["path"]
        if not ha_url or not path.startswith(PROXY_PREFIXES) or ".." in path:
            raise web.HTTPNotFound()
        target = f"{ha_url}/{path}"
        if req.query_string:
            target += "?" + req.query_string
        async with session.get(target, timeout=aiohttp.ClientTimeout(total=30)) as up:
            resp = web.StreamResponse(status=up.status)
            for header in ("Content-Type", "Cache-Control"):
                if header in up.headers:
                    resp.headers[header] = up.headers[header]
            await resp.prepare(req)
            async for chunk in up.content.iter_chunked(64 * 1024):
                await resp.write(chunk)
            await resp.write_eof()
            return resp

    @routes.get("/themes/{theme}/{filename}")
    async def theme_file(req: web.Request) -> web.StreamResponse:
        path = hub.themes.path_for(req.match_info["theme"], req.match_info["filename"])
        if not path:
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    @routes.get("/music/{path:.*}")
    async def music_file(req: web.Request) -> web.StreamResponse:
        root = music_dir.resolve()
        path = (root / req.match_info["path"]).resolve()
        if root not in path.parents or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    if hub.source.demo:
        @routes.get("/demo/{action}")
        async def demo_action(req: web.Request) -> web.Response:
            """Preview helpers, demo mode only: /demo/doorbell, /demo/alert, /demo/next."""
            action = req.match_info["action"]
            if action == "doorbell":
                hub.show_camera("camera.camera_1", "Someone's at the front door", 20)
            elif action == "alert":
                st = dict(hub.states.get("binary_sensor.weather_alert") or {})
                on = st.get("state") != "on"
                st.update(state="on" if on else "off",
                          attributes={**st.get("attributes", {}),
                                      "title": "Wind Advisory until 9 PM - gusts up to 45 mph expected"})
                hub.update_state("binary_sensor.weather_alert", st, None)
            elif action == "next":
                hub.next_screen()
            elif action.startswith("theme-"):
                hub.set_theme(action[6:])
            else:
                raise web.HTTPNotFound()
            return web.json_response({"ok": True})

    app.add_routes(routes)
    app.router.add_static("/static/", web_dir, append_version=False)
    return app
