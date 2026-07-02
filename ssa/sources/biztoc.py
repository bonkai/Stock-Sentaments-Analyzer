"""biztoc adapter — full-text FIREHOSE (Phase 1b, the revived "old way").

PLAN v2 makes biztoc a first-class deep source: harvest every latest feed link
not already in ``state/seen.json``, fetch each page, and emit records whose
``summary_or_text`` is the FULL article body. This is the WIDE bucket the
Phase-2 triage pass feeds on, so it deliberately ignores the watchlist.

The link index is the RSS feed (bounded, titled, bot-tolerant) rather than the
legacy homepage ``<a>``-scrape, which yielded untitled nav/junk links. Body
extraction ports the two-strategy BeautifulSoup logic from legacy
``get_links.scrape_article``. biztoc historically blocks bots and republishes
wire stories, so every body fetch is failure-isolated and falls back to the RSS
summary — the firehose degrades to the old summary behaviour, never to nothing.
``raw.full_text`` records which records got a real body, so yield is measurable.

Heavy deps (bs4) live ONLY in this adapter, imported function-locally — the
rest of ``ssa/`` stays RSS/API-light and importable without them.
"""

from __future__ import annotations

import logging

import feedparser

from ..record import Article, build_article

log = logging.getLogger(__name__)

SOURCE = "biztoc"
SOURCE_TYPE = "news"

_DEFAULT_FEED = "https://biztoc.com/feed"
# Full bodies are truncated to keep JSONL lines bounded (a triage pass does not
# need more than this; override via BIZTOC_MAX_BODY_CHARS).
_MAX_BODY_CHARS = 20_000


def parse_rss(text: str) -> list[Article]:
    """Parse the biztoc RSS firehose (pure)."""
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
            raw={"domain": entry.get("source", {}).get("title") if entry.get("source") else None},
        ))
    return articles


def extract_body(html: str) -> str:
    """Extract readable article text from an HTML page (pure).

    Ports the two extraction strategies of legacy ``get_links.scrape_article``:
    paragraphs inside the first article-like container, else all paragraphs.
    """
    # Function-local so `import ssa.sources` works without bs4 installed.
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    content = ""

    containers = soup.select(
        'article, [class*="article"], [class*="content"], main, [role="main"]'
    )
    if containers:
        content = " ".join(p.get_text() for p in containers[0].find_all("p"))

    if not content:
        content = " ".join(p.get_text() for p in soup.find_all("p"))

    return content.strip()


def collect_firehose(http, cfg: dict, seen) -> list[Article]:
    """Harvest the feed, then fetch the FULL BODY of every link not in ``seen``.

    ``seen`` is read-only here (pre-fetch dedup so already-processed links cost
    zero requests); the orchestrator's post-collection loop remains the single
    writer of dedup state. Per-link failures downgrade that record to its RSS
    summary instead of aborting the batch.
    """
    feed_url = cfg.get("BIZTOC_FEED", _DEFAULT_FEED)
    harvested = parse_rss(http.get_text(feed_url))

    unread = [a for a in harvested if not seen.is_seen(a.url, a.title)]
    max_articles = int(cfg.get("BIZTOC_MAX_ARTICLES", 0) or 0)
    if max_articles and len(unread) > max_articles:
        log.warning(
            "biztoc firehose capped: fetching %d of %d unread links "
            "(BIZTOC_MAX_ARTICLES=%d).", max_articles, len(unread), max_articles,
        )
        unread = unread[:max_articles]

    max_chars = int(cfg.get("BIZTOC_MAX_BODY_CHARS", _MAX_BODY_CHARS))
    records: list[Article] = []
    n_full = n_fallback = n_errors = 0
    for art in unread:
        body = ""
        try:
            resp = http.get(art.url)
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if not ctype or "html" in ctype:  # don't soup PDFs/JSON/images
                body = extract_body(resp.text)
        except Exception as exc:  # one dead/blocked link must not kill the batch
            n_errors += 1
            log.debug("biztoc body fetch failed for %s: %s", art.url, exc)

        if body:
            n_full += 1
        else:
            n_fallback += 1

        records.append(build_article(
            source=SOURCE,
            source_type=SOURCE_TYPE,
            url=art.url,
            title=art.title,
            summary_or_text=body[:max_chars] if body else art.summary_or_text,
            published=art.published,
            raw={**art.raw, "full_text": bool(body)},
        ))

    log.info(
        "biztoc firehose: %d in feed, %d unread; %d full-text, "
        "%d summary-fallback (of which %d fetch errors).",
        len(harvested), len(unread), n_full, n_fallback, n_errors,
    )
    return records
