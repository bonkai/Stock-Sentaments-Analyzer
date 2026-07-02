"""Article record: the pinned Phase-1 schema, date parsing, and JSONL writer.

Schema is pinned by PLAN.md and must not drift (later phases add ticker/sector
tags and sentiment as *new* fields; Phase 1 leaves them out):

    {
      "id": "sha1(canonical_url|normalized_title)",
      "source": "edgar|yahoo-rss|gdelt|dcd-rss|utilitydive-rss|semieng-rss|biztoc|apewisdom",
      "source_type": "news|social|filing",
      "url": "canonical url",
      "title": "...",
      "published": "ISO-8601 or null",
      "fetched_at": "ISO-8601",
      "summary_or_text": "headline/excerpt/body if available",
      "raw": { ...source-specific extras (CIK, form type, mention counts)... }
    }
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

from .dedup import canonicalize_url, make_id, normalize_title

log = logging.getLogger(__name__)

# Allowed enum values, validated at build time so a typo in an adapter surfaces
# immediately rather than polluting the dataset.
SOURCE_TYPES = {"news", "social", "filing"}
SOURCES = {
    "edgar", "yahoo-rss", "gdelt", "dcd-rss", "utilitydive-rss",
    "semieng-rss", "biztoc", "apewisdom",
}


def now_utc_iso() -> str:
    """Timezone-aware UTC timestamp (NOT the deprecated naive utcnow())."""
    return datetime.now(timezone.utc).isoformat()


def today_utc() -> str:
    """UTC date string for the output filename — UTC everywhere avoids a
    midnight rollover splitting one logical run across two files."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def parse_date(value: Any) -> Optional[str]:
    """Best-effort parse of a published date into ISO-8601 UTC, else None.

    Handles RFC-822 (RSS pubDate), ISO-8601 (Atom updated / EDGAR), and the
    GDELT compact ``YYYYMMDDTHHMMSSZ`` form. A naive datetime is assumed UTC.
    Anything unparseable returns None (the schema explicitly permits null).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        dt = _parse_date_string(s)
        if dt is None:
            log.debug("Unparseable date: %r", value)
            return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_date_string(s: str) -> Optional[datetime]:
    # GDELT compact form: 20260623T120000Z
    if len(s) == 16 and s[8] == "T" and s.endswith("Z") and s[:8].isdigit():
        try:
            return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    # ISO-8601 (handle trailing Z which older fromisoformat rejects).
    iso = s.replace("Z", "+00:00") if s.endswith("Z") else s
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        pass
    # RFC-822 (RSS pubDate): Mon, 23 Jun 2026 12:00:00 GMT
    try:
        return parsedate_to_datetime(s)
    except (TypeError, ValueError):
        return None


@dataclass
class Article:
    """One normalized article record. Field order matches the pinned schema."""

    id: str
    source: str
    source_type: str
    url: str
    title: str
    published: Optional[str]
    fetched_at: str
    summary_or_text: str
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json_line(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def build_article(
    *,
    source: str,
    source_type: str,
    url: str,
    title: str,
    summary_or_text: str = "",
    published: Any = None,
    raw: Optional[dict] = None,
    fetched_at: Optional[str] = None,
) -> Article:
    """Construct an :class:`Article`, computing id and canonicalizing the URL.

    ``url`` is stored canonicalized (schema says "canonical url"); ``title`` is
    kept as the original display string; ``published`` is normalized to ISO-8601
    UTC or None. Source / source_type are validated against the allowed enums.
    """
    if source not in SOURCES:
        raise ValueError(f"Unknown source {source!r}; allowed: {sorted(SOURCES)}")
    if source_type not in SOURCE_TYPES:
        raise ValueError(
            f"Unknown source_type {source_type!r}; allowed: {sorted(SOURCE_TYPES)}"
        )

    title = (title or "").strip()
    canon = canonicalize_url(url)
    return Article(
        id=make_id(url, title),
        source=source,
        source_type=source_type,
        url=canon,
        title=title,
        published=parse_date(published),
        fetched_at=fetched_at or now_utc_iso(),
        summary_or_text=(summary_or_text or "").strip(),
        raw=raw or {},
    )


def append_jsonl(path: str, articles: list[Article]) -> int:
    """Append articles to a dated JSONL file (one record per line).

    The file is opened in append mode so re-runs add only new records. Returns
    the number of lines written. The directory is created if needed.
    """
    if not articles:
        return 0
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for art in articles:
            f.write(art.to_json_line() + "\n")
    return len(articles)


# Re-export so adapters can `from ..record import normalize_title` if useful.
__all__ = [
    "Article", "build_article", "append_jsonl", "parse_date",
    "now_utc_iso", "today_utc", "canonicalize_url", "normalize_title",
    "SOURCES", "SOURCE_TYPES",
]
