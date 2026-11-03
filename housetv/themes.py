"""Themes: folders containing theme.json plus optional background media.

Built-in themes ship in /app/themes. Drop your own folder into
/config/themes/<name>/ (same layout) to add or override one.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)


class Themes:
    def __init__(self, builtin_dir: Path, user_dir: Path):
        self.dirs = [builtin_dir, user_dir]  # later wins
        self.themes: dict[str, dict] = {}

    def scan(self) -> None:
        found: dict[str, dict] = {}
        for base in self.dirs:
            if not base.is_dir():
                continue
            for folder in sorted(p for p in base.iterdir() if p.is_dir()):
                meta_path = folder / "theme.json"
                if not meta_path.exists():
                    continue
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as err:
                    log.warning("Skipping theme %s: %s", folder.name, err)
                    continue
                meta["id"] = folder.name
                meta.setdefault("name", folder.name.title())
                meta["base_url"] = f"/themes/{folder.name}/"
                if (folder / "theme.css").exists():
                    meta["css"] = f"/themes/{folder.name}/theme.css"
                found[folder.name] = meta
        self.themes = found

    def path_for(self, theme_id: str, filename: str) -> Path | None:
        for base in reversed(self.dirs):
            candidate = (base / theme_id / filename).resolve()
            if candidate.is_file() and base.resolve() in candidate.parents:
                return candidate
        return None

    def resolve(self, cfg: dict, override: str | None, today: date | None = None) -> dict:
        today = today or date.today()
        theme_id = None
        if override and override in self.themes:
            theme_id = override
        if theme_id is None:
            theme_id = scheduled_theme(cfg["theme"].get("schedule", []), today)
        if theme_id not in self.themes:
            theme_id = cfg["theme"].get("default")
        if theme_id not in self.themes:
            theme_id = "night" if "night" in self.themes else next(iter(self.themes), None)
        return self.themes.get(theme_id, {"id": "none", "name": "None"})


def _md(text: str) -> tuple[int, int]:
    month, day = str(text).split("-")
    return int(month), int(day)


def scheduled_theme(schedule: list[dict], today: date) -> str | None:
    """First schedule entry whose MM-DD range contains today (ranges may wrap the year)."""
    cur = (today.month, today.day)
    for entry in schedule:
        try:
            start, end = _md(entry["from"]), _md(entry["to"])
        except (KeyError, ValueError):
            log.warning("Bad theme schedule entry %s (use from: \"MM-DD\", to: \"MM-DD\")", entry)
            continue
        inside = start <= cur <= end if start <= end else (cur >= start or cur <= end)
        if inside:
            return entry["theme"]
    return None
