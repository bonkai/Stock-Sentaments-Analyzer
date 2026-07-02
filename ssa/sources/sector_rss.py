"""Sector RSS adapter — datacenter / power / semiconductor trade press.

Reads a config-driven list of feeds (DataCenter Dynamics, Utility Dive,
Semiconductor Engineering by default), each tagged with its own ``source`` value
(``dcd-rss`` / ``utilitydive-rss`` / ``semieng-rss``). Standard RSS 2.0, parsed
with feedparser. Per-feed failure is isolated so one dead feed doesn't sink the
others — PLAN requires only that *one* sector feed work end-to-end.
"""

from __future__ import annotations

import logging

import feedparser

from ..record import SOURCES, Article, build_article

log = logging.getLogger(__name__)

SOURCE_TYPE = "news"

# (source-name, feed-url) — source-name must be in record.SOURCES.
_DEFAULT_FEEDS = [
    {"source": "dcd-rss", "url": "https://www.datacenterdynamics.com/en/rss/"},
    {"source": "utilitydive-rss", "url": "https://www.utilitydive.com/feeds/news/"},
    {"source": "semieng-rss", "url": "https://semiengineering.com/feed/"},
]


def parse_rss(text: str, source: str) -> list[Article]:
    """Parse one sector RSS feed (pure). ``source`` tags the records."""
    if source not in SOURCES:
        raise ValueError(f"sector_rss: unknown source {source!r}")
    feed = feedparser.parse(text)
    articles: list[Article] = []
    for entry in feed.entries:
        link = entry.get("link", "")
        title = entry.get("title", "").strip()
        if not link or not title:
            continue
        articles.append(build_article(
            source=source,
            source_type=SOURCE_TYPE,
            url=link,
            title=title,
            summary_or_text=entry.get("summary", "") or entry.get("description", ""),
            published=entry.get("published") or entry.get("updated"),
            raw={"feed": source},
        ))
    return articles


def collect(http, cfg: dict, watchlist=None) -> list[Article]:
    feeds = cfg.get("SECTOR_RSS_FEEDS", _DEFAULT_FEEDS)
    out: list[Article] = []
    for feed in feeds:
        source, url = feed.get("source"), feed.get("url")
        if not source or not url:
            continue
        try:
            text = http.get_text(url)
            records = parse_rss(text, source)
            out.extend(records)
            log.info("Sector RSS %s: %d records.", source, len(records))
        except Exception as exc:  # isolate per-feed
            log.warning("Sector RSS %s failed: %s", source, exc)
    return out
