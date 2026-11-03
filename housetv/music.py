"""Background music library: every audio file under the music folder."""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger(__name__)

AUDIO_EXT = {".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wav"}


def _tags(path: Path) -> tuple[str | None, str | None]:
    try:
        from mutagen import File as MutagenFile  # lazy: optional nicety
        audio = MutagenFile(path, easy=True)
        if audio and audio.tags:
            title = (audio.tags.get("title") or [None])[0]
            artist = (audio.tags.get("artist") or [None])[0]
            return title, artist
    except Exception:  # noqa: BLE001 - bad tags shouldn't break the library
        pass
    return None, None


class MusicLibrary:
    def __init__(self, root: Path):
        self.root = root
        self._cache: dict[str, tuple[float, dict]] = {}
        self.tracks: list[dict] = []

    def scan(self) -> bool:
        """Rescan the folder. Returns True if the track list changed."""
        if not self.root.is_dir():
            changed = bool(self.tracks)
            self.tracks = []
            return changed
        tracks = []
        for path in sorted(self.root.rglob("*")):
            if path.suffix.lower() not in AUDIO_EXT or not path.is_file():
                continue
            rel = path.relative_to(self.root).as_posix()
            mtime = path.stat().st_mtime
            cached = self._cache.get(rel)
            if cached and cached[0] == mtime:
                tracks.append(cached[1])
                continue
            title, artist = _tags(path)
            info = {
                "url": "/music/" + quote(rel),
                "title": title or path.stem.replace("_", " "),
                "artist": artist,
            }
            self._cache[rel] = (mtime, info)
            tracks.append(info)
        changed = tracks != self.tracks
        self.tracks = tracks
        if changed:
            log.info("Music library: %d tracks", len(tracks))
        return changed
