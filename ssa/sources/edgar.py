"""SEC EDGAR adapter — recent filings via the ``getcurrent`` Atom feed.

Zero-key, but SEC fair-access REQUIRES a stable, descriptive User-Agent that
carries a real contact email. We therefore pin the UA from config
(``EDGAR_USER_AGENT`` / ``EDGAR_CONTACT``) and warn loudly if it still looks
like a placeholder — a bad/rotating UA risks an SEC IP block.

We pull *recent* filings broadly (universe filtering is Phase-2 ticker matching,
explicitly out of scope here). source_type is ``filing``.
"""

from __future__ import annotations

import logging
import re

import feedparser

from ..record import Article, build_article

log = logging.getLogger(__name__)

SOURCE = "edgar"
SOURCE_TYPE = "filing"

_DEFAULT_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent"
    "&type={form}&company=&dateb=&owner=include&count={count}&output=atom"
)
_CIK_RE = re.compile(r"\((\d{7,10})\)")
_ACCESSION_RE = re.compile(r"accession-number=([\d-]+)")
_PLACEHOLDER_HINTS = ("example.com", "replace_me", "your_email", "changeme", "test@test")


def _edgar_user_agent(cfg: dict) -> str:
    ua = (cfg.get("EDGAR_USER_AGENT") or "").strip()
    if not ua:
        contact = (cfg.get("EDGAR_CONTACT") or "").strip()
        ua = f"stock-sentaments-ssa/0.1 ({contact})" if contact else "stock-sentaments-ssa/0.1"
    if any(hint in ua.lower() for hint in _PLACEHOLDER_HINTS):
        log.warning(
            "EDGAR User-Agent looks like a PLACEHOLDER (%r). SEC fair-access "
            "requires a real contact email; replace EDGAR_CONTACT in config.json "
            "before relying on EDGAR — a bad UA risks an IP block.", ua,
        )
    return ua


def parse_atom(text: str) -> list[Article]:
    """Parse an EDGAR getcurrent Atom feed into filing records (pure)."""
    feed = feedparser.parse(text)
    articles: list[Article] = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "")
        if not link:
            continue
        published = entry.get("updated") or entry.get("published")

        cik_match = _CIK_RE.search(title)
        # Form type is usually the leading token of the title ("8-K - Foo Inc..")
        # or the atom category term.
        form = ""
        if entry.get("tags"):
            form = entry["tags"][0].get("term", "")
        if not form and " - " in title:
            form = title.split(" - ", 1)[0].strip()

        acc = ""
        if entry.get("id"):
            m = _ACCESSION_RE.search(entry["id"])
            if m:
                acc = m.group(1)

        raw = {
            "form": form,
            "cik": cik_match.group(1) if cik_match else None,
            "accession": acc,
            "edgar_id": entry.get("id"),
        }
        articles.append(build_article(
            source=SOURCE,
            source_type=SOURCE_TYPE,
            url=link,
            title=title,
            summary_or_text=entry.get("summary", "") or title,
            published=published,
            raw=raw,
        ))
    return articles


def collect(http, cfg: dict, watchlist=None) -> list[Article]:
    form = cfg.get("EDGAR_FORM_TYPE", "8-K")
    count = int(cfg.get("EDGAR_COUNT", 40))
    url = cfg.get("EDGAR_URL") or _DEFAULT_URL.format(form=form, count=count)
    ua = _edgar_user_agent(cfg)
    text = http.get_text(url, user_agent=ua)
    return parse_atom(text)
