"""ApeWisdom adapter — social mention counts (the SOCIAL bucket, no API key).

ApeWisdom is a ticker-mention-count aggregator, NOT an article source, so each
row is coerced into the schema: a synthetic url/title and the real numbers parked
in ``raw`` (the schema explicitly anticipates "mention counts" in raw).
``source_type=social`` keeps it in a separate bucket from news.

A daily ``snapshot`` date is baked into the synthetic URL so the *same* ticker on
a *different* day is a distinct record (mentions change daily), while a same-day
re-run collapses to one (idempotent). This adapter carries ticker symbols, but
that's social signal provenance, not Phase-2 ticker matching.
"""

from __future__ import annotations

import logging

from ..record import Article, build_article, today_utc

log = logging.getLogger(__name__)

SOURCE = "apewisdom"
SOURCE_TYPE = "social"

_ENDPOINT = "https://apewisdom.io/api/v1.0/filter/{filter}/page/{page}"


def parse_json(data: dict, snapshot_date: str, top_n: int = 50) -> list[Article]:
    """Parse an ApeWisdom filter payload into social records (pure).

    ``snapshot_date`` (UTC YYYY-MM-DD) makes each day's snapshot distinct.
    """
    rows = (data or {}).get("results", [])[: max(0, top_n)]
    articles: list[Article] = []
    for row in rows:
        ticker = (row.get("ticker") or "").strip()
        if not ticker:
            continue
        name = (row.get("name") or "").strip()
        mentions = row.get("mentions")
        rank = row.get("rank")
        upvotes = row.get("upvotes")
        rank_prev = row.get("rank_24h_ago")
        mentions_prev = row.get("mentions_24h_ago")

        url = f"https://apewisdom.io/stocks/{ticker}/?snapshot={snapshot_date}"
        title = f"{ticker} {name}: {mentions} mentions (rank {rank})".strip()
        summary = (
            f"{ticker} ({name}) had {mentions} social mentions and {upvotes} "
            f"upvotes; rank {rank} (was {rank_prev} 24h ago, {mentions_prev} "
            f"mentions 24h ago)."
        )
        articles.append(build_article(
            source=SOURCE,
            source_type=SOURCE_TYPE,
            url=url,
            title=title,
            summary_or_text=summary,
            published=None,  # no per-row timestamp; snapshot date lives in url/raw
            raw={
                "ticker": ticker,
                "name": name,
                "mentions": mentions,
                "upvotes": upvotes,
                "rank": rank,
                "rank_24h_ago": rank_prev,
                "mentions_24h_ago": mentions_prev,
                "snapshot": snapshot_date,
            },
        ))
    return articles


def collect(http, cfg: dict, watchlist=None) -> list[Article]:
    filt = cfg.get("APEWISDOM_FILTER", "all-stocks")
    top_n = int(cfg.get("APEWISDOM_TOP_N", 50))
    url = _ENDPOINT.format(filter=filt, page=1)
    data = http.get_json(url)
    return parse_json(data, snapshot_date=today_utc(), top_n=top_n)
