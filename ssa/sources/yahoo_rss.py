"""Yahoo Finance per-ticker RSS adapter.

Fetches ``https://feeds.finance.yahoo.com/rss/2.0/headline?s=<TICKER>`` for each
ticker in the watchlist. This is the one place a ticker list is needed in
Phase 1 — NOT for matching, only to address the per-ticker feed. The watchlist
is provisional, user-owned config (see PROVISIONAL banner in watchlist.json).
"""

from __future__ import annotations

import logging

import feedparser

from ..record import Article, build_article

log = logging.getLogger(__name__)

SOURCE = "yahoo-rss"
SOURCE_TYPE = "news"

_FEED = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"


def parse_rss(text: str, ticker: str) -> list[Article]:
    """Parse a Yahoo headline RSS feed for one ticker (pure)."""
    feed = feedparser.parse(text)
    articles: list[Article] = []
    for entry in feed.entries:
        link = entry.get("link", "")
        title = entry.get("title", "").strip()
        if not link or not title:
            continue
        articles.append(build_article(
            source=SOURCE,
            source_type=SOURCE_TYPE,
            url=link,
            title=title,
            summary_or_text=entry.get("summary", "") or entry.get("description", ""),
            published=entry.get("published") or entry.get("updated"),
            raw={"ticker": ticker, "guid": entry.get("id")},
        ))
    return articles


def collect(http, cfg: dict, watchlist=None) -> list[Article]:
    tickers = list(watchlist or [])
    cap = cfg.get("YAHOO_MAX_TICKERS")
    if cap:
        tickers = tickers[: int(cap)]
    if not tickers:
        log.warning("Yahoo RSS: empty watchlist — no tickers to query.")
        return []

    template = cfg.get("YAHOO_FEED_TEMPLATE", _FEED)
    # Circuit breaker: if the endpoint hard-blocks our IP (Yahoo commonly 429s
    # server IPs), stop after N consecutive failures rather than hammering it
    # once per ticker. A single bad symbol won't trip it.
    max_consecutive = int(cfg.get("YAHOO_MAX_CONSECUTIVE_FAILURES", 3))
    out: list[Article] = []
    failures = 0
    consecutive = 0
    for ticker in tickers:
        url = template.format(ticker=ticker)
        try:
            text = http.get_text(url)
            out.extend(parse_rss(text, ticker))
            consecutive = 0
        except Exception as exc:  # isolate per-ticker so one bad symbol isn't fatal
            failures += 1
            consecutive += 1
            log.warning("Yahoo RSS failed for %s: %s", ticker, exc)
            if consecutive >= max_consecutive:
                log.warning(
                    "Yahoo RSS: %d consecutive failures — endpoint appears to be "
                    "blocking this IP; skipping remaining %d tickers.",
                    consecutive, len(tickers) - tickers.index(ticker) - 1,
                )
                break
    if failures:
        log.info("Yahoo RSS: %d ticker feeds failed; %d records collected.",
                 failures, len(out))
    return out
