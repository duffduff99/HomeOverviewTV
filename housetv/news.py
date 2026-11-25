"""Headlines from RSS feeds, and Wikipedia's "On this day".

The server fetches these (the TV's browser never talks to the internet), so
only the server needs access to the feed hosts. Default hosts to allow:
  news.google.com (AP), feeds.npr.org, feeds.bbci.co.uk, en.wikipedia.org
"""
from __future__ import annotations

import html
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import aiohttp

from . import __version__

log = logging.getLogger(__name__)

# Wikimedia asks API clients to identify themselves.
USER_AGENT = f"HouseTV/{__version__} (+https://github.com/duffduff99/HomeOverviewTV)"
MAX_BYTES = 3 * 1024 * 1024

DEFAULT_FEEDS = [
    # AP has no official RSS feed; this is Google News limited to apnews.com.
    {"name": "AP", "url": "https://news.google.com/rss/search?q=site:apnews.com+when:1d&hl=en-US&gl=US&ceid=US:en"},
    {"name": "NPR", "url": "https://feeds.npr.org/1001/rss.xml"},
    {"name": "BBC", "url": "https://feeds.bbci.co.uk/news/rss.xml"},
]

_TAG_RE = re.compile(r"<[^>]+>")


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return html.unescape(_TAG_RE.sub("", el.text)).strip()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: ET.Element, name: str) -> ET.Element | None:
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)          # RSS: RFC 822
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))   # Atom: ISO 8601
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_feed(xml_bytes: bytes, source: str) -> list[dict]:
    """RSS 2.0 or Atom -> [{title, source, published (ISO) or None}]."""
    root = ET.fromstring(xml_bytes)
    items = [el for el in root.iter() if _local(el.tag) in ("item", "entry")]
    out = []
    for it in items:
        title = _text(_child(it, "title"))
        if not title:
            continue
        # Google News appends " - Publisher" to every title; drop it.
        publisher = _text(_child(it, "source"))
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3].rstrip()
        when = None
        for name in ("pubDate", "published", "updated", "date"):
            node = _child(it, name)
            if node is not None:
                when = _parse_date(_text(node))
                if when:
                    break
        out.append({"title": title, "source": source,
                    "published": when.isoformat() if when else None})
    return out


def merge_headlines(per_feed: list[list[dict]], limit: int, max_age_hours: float,
                    now: datetime | None = None) -> list[dict]:
    """Newest first within each feed, then take turns between feeds so every
    source gets a fair share, skipping stale items and repeated titles."""
    now = now or datetime.now(timezone.utc)
    queues = []
    for items in per_feed:
        fresh = []
        for it in items:
            if it["published"]:
                age_h = (now - datetime.fromisoformat(it["published"])).total_seconds() / 3600
                if age_h > max_age_hours:
                    continue
            fresh.append(it)
        fresh.sort(key=lambda x: x["published"] or "", reverse=True)
        queues.append(fresh)
    out, seen = [], set()
    while len(out) < limit and any(queues):
        for q in queues:
            while q:
                it = q.pop(0)
                key = it["title"].lower()
                if key not in seen:
                    seen.add(key)
                    out.append(it)
                    break
            if len(out) >= limit:
                break
    return out


def parse_on_this_day(data: dict, count: int) -> list[dict]:
    events = []
    for ev in (data or {}).get("selected", []) or []:
        text = (ev.get("text") or "").strip()
        if text and ev.get("year") is not None:
            events.append({"year": ev["year"], "text": text})
    # A spread across the centuries reads better than the first few listed.
    events.sort(key=lambda e: e["year"])
    if len(events) > count:
        step = len(events) / count
        events = [events[int(i * step)] for i in range(count)]
    return events


async def _get(session: aiohttp.ClientSession, url: str) -> bytes:
    async with session.get(url, headers={"User-Agent": USER_AGENT},
                           timeout=aiohttp.ClientTimeout(total=20)) as resp:
        resp.raise_for_status()
        # Read to the end: responses arrive in pieces, and content.read(n) only
        # returns what has arrived so far. Stop if it grows past MAX_BYTES.
        body = bytearray()
        async for chunk in resp.content.iter_chunked(64 * 1024):
            body += chunk
            if len(body) > MAX_BYTES:
                raise ValueError("response too large")
        return bytes(body)


async def fetch_headlines(session: aiohttp.ClientSession, feeds: list[dict], limit: int,
                          max_age_hours: float) -> list[dict]:
    per_feed = []
    for feed in feeds:
        name = feed.get("name") or feed.get("url", "")
        try:
            per_feed.append(parse_feed(await _get(session, feed["url"]), name))
        except Exception as err:  # noqa: BLE001 - one bad feed shouldn't hide the others
            log.warning("Headlines from %s failed: %s", name, err)
            per_feed.append([])
    return merge_headlines(per_feed, limit, max_age_hours)


async def fetch_on_this_day(session: aiohttp.ClientSession, day: date, count: int,
                            language: str = "en") -> list[dict]:
    url = (f"https://{language}.wikipedia.org/api/rest_v1/feed/onthisday/selected/"
           f"{day.month:02d}/{day.day:02d}")
    return parse_on_this_day(json.loads(await _get(session, url)), count)


DEMO_HEADLINES = [
    ("City council approves new riverfront park after two-year debate", "AP", 1),
    ("Scientists map the deepest part of the ocean in unprecedented detail", "NPR", 2),
    ("Markets steady as investors weigh latest inflation figures", "BBC", 2),
    ("Wildfire crews gain ground as cooler weather moves in", "AP", 3),
    ("How a small-town library became the heart of its community", "NPR", 4),
    ("Space agency confirms launch date for next lunar mission", "BBC", 5),
    ("High school robotics team heads to world championship", "AP", 6),
    ("New study links daily walks to better sleep", "NPR", 7),
]
DEMO_ON_THIS_DAY = [
    {"year": 1859, "text": "Charles Darwin publishes On the Origin of Species."},
    {"year": 1963, "text": "Lee Harvey Oswald is shot dead by Jack Ruby in Dallas, live on television."},
    {"year": 1974, "text": "The 3.2-million-year-old skeleton of \"Lucy\" is discovered in Ethiopia."},
]


def demo_headlines(limit: int) -> list[dict]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return [{"title": t, "source": s, "published": (now - timedelta(hours=h)).isoformat()}
            for t, s, h in DEMO_HEADLINES][:limit]
