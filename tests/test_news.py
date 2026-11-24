from datetime import datetime, timezone

from housetv.news import merge_headlines, parse_feed, parse_on_this_day

NPR_STYLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>NPR Topics: News</title>
<item><title>Storm brings heavy snow to the Rockies</title><link>https://www.npr.org/a</link>
  <pubDate>Tue, 24 Nov 2026 14:05:00 -0500</pubDate></item>
<item><title><![CDATA[Budget talks resume &amp; deadline nears]]></title>
  <pubDate>Tue, 24 Nov 2026 09:00:00 -0500</pubDate></item>
<item><title></title></item>
</channel></rss>"""

GOOGLE_NEWS_STYLE = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><title>Senate passes infrastructure bill - AP News</title>
  <link>https://news.google.com/rss/articles/x</link>
  <pubDate>Tue, 24 Nov 2026 18:30:00 GMT</pubDate>
  <source url="https://apnews.com">AP News</source></item>
</channel></rss>"""

ATOM_STYLE = b"""<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom headline</title><updated>2026-11-24T12:00:00Z</updated></entry></feed>"""


def test_parse_rss_and_strip_html_entities():
    items = parse_feed(NPR_STYLE, "NPR")
    assert [i["title"] for i in items] == ["Storm brings heavy snow to the Rockies", "Budget talks resume & deadline nears"]
    assert items[0]["source"] == "NPR"
    assert items[0]["published"].startswith("2026-11-24T14:05:00-05:00")


def test_google_news_publisher_suffix_removed():
    items = parse_feed(GOOGLE_NEWS_STYLE, "AP")
    assert items[0]["title"] == "Senate passes infrastructure bill"


def test_atom_feed():
    items = parse_feed(ATOM_STYLE, "X")
    assert items[0]["title"] == "Atom headline" and items[0]["published"].startswith("2026-11-24T12:00")


def test_merge_takes_turns_skips_old_and_duplicates():
    now = datetime(2026, 11, 24, 20, 0, tzinfo=timezone.utc)
    iso = lambda h: datetime(2026, 11, 24, h, 0, tzinfo=timezone.utc).isoformat()  # noqa: E731
    a = [{"title": "A1", "source": "A", "published": iso(19)}, {"title": "A2", "source": "A", "published": iso(18)},
         {"title": "A3", "source": "A", "published": iso(17)}]
    b = [{"title": "Shared", "source": "B", "published": iso(19)}, {"title": "B-old", "source": "B",
         "published": datetime(2026, 11, 20, tzinfo=timezone.utc).isoformat()}]
    c = [{"title": "shared", "source": "C", "published": iso(19)}, {"title": "C2", "source": "C", "published": None}]
    out = merge_headlines([a, b, c], limit=5, max_age_hours=24, now=now)
    assert [i["title"] for i in out] == ["A1", "Shared", "C2", "A2", "A3"]


def test_on_this_day_spread():
    data = {"selected": [{"year": y, "text": f"Event {y}"} for y in (2001, 1066, 1969, 1776, 1989, 1914)]
            + [{"text": "no year"}]}
    out = parse_on_this_day(data, 3)
    assert [e["year"] for e in out] == [1066, 1914, 1989]
