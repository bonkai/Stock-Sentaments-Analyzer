"""ssa — Stock Sentiment Analyzer (fresh rebuild).

Phase 1: the scraper. Fetches the locked zero-key news/social/filing sources,
normalizes them into deduped article records, and writes
``outputs/articles_<YYYY-MM-DD>.jsonl``.

Run with::

    python -m ssa.scrape

This package is intentionally independent of the legacy Ollama pipeline at the
repo root (get_links.py / extract_tickers.py / app.py). It does NOT do ticker
matching (Phase 2), scoring (Phase 3), or the dashboard (Phase 4).
"""

__all__ = ["scrape", "dedup", "record", "http", "sources"]
