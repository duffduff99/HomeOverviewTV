"""Entry point.

    python -m housetv                 run the channel server
    python -m housetv --demo          run with built-in fake data (no Home Assistant needed)
    python -m housetv entities [text] list Home Assistant entity ids to help write config.yaml
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import aiohttp
from aiohttp import web

from .config import load
from .ha import HAClient
from .hub import Hub
from .music import MusicLibrary
from .server import build_app
from .sources import DemoSource, HASource
from .themes import Themes

APP_DIR = Path(__file__).resolve().parent.parent
log = logging.getLogger("housetv")


def _paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    config_dir = Path(args.config_dir or os.environ.get("CONFIG_DIR", APP_DIR / "config"))
    music_dir = Path(args.music_dir or os.environ.get("MUSIC_DIR", config_dir.parent / "music"))
    return config_dir, music_dir, config_dir / "config.yaml"


async def run_server(args: argparse.Namespace) -> None:
    config_dir, music_dir, config_path = _paths(args)
    demo = args.demo or os.environ.get("DEMO", "").lower() in ("1", "true", "yes")
    if not config_path.exists():
        example = APP_DIR / "config" / "config.example.yaml"
        if demo:
            config_path = example
        else:
            log.warning("No %s yet - copy config.example.yaml to get started", config_path)
    cfg = load(config_path)
    session = aiohttp.ClientSession()
    ha = cfg["homeassistant"]
    if demo:
        log.info("Running in DEMO mode with fake data")
        source = DemoSource()
    elif ha.get("url") and ha.get("token"):
        source = HASource(ha["url"], ha["token"], session)
    else:
        log.error("Home Assistant URL/token missing. Set HA_URL and HA_TOKEN, "
                  "or start with --demo to try it out.")
        sys.exit(2)

    themes = Themes(APP_DIR / "themes", config_dir / "themes")
    hub = Hub(config_path, source, themes, MusicLibrary(music_dir))
    await hub.start()

    if cfg["mqtt"].get("enabled") and cfg["mqtt"].get("host") and not demo:
        from .mqtt import MqttBridge
        asyncio.create_task(MqttBridge(hub).run())

    app = build_app(hub, APP_DIR / "web", music_dir, session)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    port = int(os.environ.get("PORT", args.port))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("House TV is on http://0.0.0.0:%d  (config: %s, music: %s)", port, config_path, music_dir)
    await asyncio.Event().wait()


async def list_entities(args: argparse.Namespace) -> None:
    _, _, config_path = _paths(args)
    ha = load(config_path)["homeassistant"]
    if not (ha.get("url") and ha.get("token")):
        sys.exit("Set HA_URL and HA_TOKEN first.")
    async with aiohttp.ClientSession() as session:
        client = HAClient(ha["url"], ha["token"], session)
        client.on_connect.append(lambda: _print_states(client, args.filter))
        try:
            await asyncio.wait_for(client.run_forever(), 30)
        except (asyncio.TimeoutError, SystemExit):
            pass


async def _print_states(client: HAClient, needle: str | None) -> None:
    states = await client.call("get_states")
    needle = (needle or "").lower()
    rows = []
    for s in sorted(states, key=lambda x: x["entity_id"]):
        name = s.get("attributes", {}).get("friendly_name", "")
        unit = s.get("attributes", {}).get("unit_of_measurement", "")
        if needle and needle not in s["entity_id"].lower() and needle not in name.lower():
            continue
        rows.append(f"{s['entity_id']:<55} {str(s['state'])[:18]:<18} {unit:<6} {name}")
    print("\n".join(rows) or "No matching entities.")
    raise SystemExit(0)


def main() -> None:
    parser = argparse.ArgumentParser(prog="housetv", description="House TV channel server")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "entities"])
    parser.add_argument("filter", nargs="?", help="text to filter entity list")
    parser.add_argument("--demo", action="store_true", help="use fake data instead of Home Assistant")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--config-dir")
    parser.add_argument("--music-dir")
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    try:
        asyncio.run(list_entities(args) if args.command == "entities" else run_server(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
