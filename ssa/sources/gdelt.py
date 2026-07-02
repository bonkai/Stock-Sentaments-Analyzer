"""GDELT DOC 2.0 adapter — global news, no API key.

IMPORTANT: GDELT returns its OWN JSON (mode=ArtList&format=json), NOT RSS — so it
gets a JSON parser, not feedparser. Dates arrive as the compact
``YYYYMMDDTHHMMSSZ`` ``seendate`` form (handled by record.parse_date).
"""

from __future__ import annotations

import json
import logging

from ..record import Article, build_article

log = logging.getLogger(__name__)

SOURCE = "gdelt"
SOURCE_TYPE = "news"

_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
# Thesis-aligned default query (AI-buildout: AI semis + datacenter power/grid).
# Space = AND, OR is explicit, quotes = phrase. Kept in config so it's tunable.
_DEFAULT_QUERY = (
    '("data center" OR "data centre" OR datacenter OR "AI chip" OR '
    '"AI accelerator" OR hyperscaler OR "grid capacity") sourcelang:english'
)


def parse_json(data) -> list[Article]:
    """Parse a GDELT DOC ArtList JSON payload (pure).

    Accepts either a dict (already-decoded) or a raw JSON string. GDELT
    occasionally returns non-JSON (HTML throttle notice) — callers should guard,
    but we also tolerate a string here.
    """
    if isinstance(data, (str, bytes)):
        data = json.loads(data)
    articles: list[Article] = []
    for art in (data or {}).get("articles", []):
        url = art.get("url", "")
        title = (art.get("title") or "").strip()
        if not url or not title:
            continue
        articles.append(build_article(
            source=SOURCE,
            source_type=SOURCE_TYPE,
            url=url,
            title=title,
            summary_or_text=title,  # GDELT ArtList gives no body, only headline
            published=art.get("seendate"),
            raw={
                "domain": art.get("domain"),
                "language": art.get("language"),
                "sourcecountry": art.get("sourcecountry"),
                "seendate": art.get("seendate"),
            },
        ))
    return articles


def collect(http, cfg: dict, watchlist=None) -> list[Article]:
    params = {
        "query": cfg.get("GDELT_QUERY", _DEFAULT_QUERY),
        "mode": "ArtList",
        "format": "json",
        "maxrecords": int(cfg.get("GDELT_MAXRECORDS", 75)),
        "sort": "DateDesc",
        "timespan": cfg.get("GDELT_TIMESPAN", "1d"),
    }
    endpoint = cfg.get("GDELT_ENDPOINT", _ENDPOINT)
    resp = http.get(endpoint, params=params)
    # GDELT returns text/plain JSON; guard against throttle/HTML responses.
    ctype = resp.headers.get("Content-Type", "")
    if "json" not in ctype and not resp.text.lstrip().startswith("{"):
        log.warning("GDELT returned non-JSON (%s) — likely throttled; skipping.", ctype)
        return []
    try:
        return parse_json(resp.json())
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("GDELT JSON decode failed: %s", exc)
        return []
