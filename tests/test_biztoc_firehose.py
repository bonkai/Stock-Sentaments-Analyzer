"""Phase-1b biztoc firehose tests: link harvest, body extraction, dedup.

No live-endpoint calls — the feed and every page come from tests/fixtures/,
served through a fake HttpClient stand-in.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import load_fixture  # noqa: E402
from ssa import sources  # noqa: E402
from ssa.dedup import SeenState  # noqa: E402
from ssa.sources import biztoc  # noqa: E402

NVDA_URL = "https://biztoc.com/x/abc123def"
CEG_URL = "https://biztoc.com/x/zzz999"
NVDA_TITLE = "Nvidia hits record as data center demand surges"


class _FakeResponse:
    def __init__(self, text, content_type="text/html; charset=utf-8"):
        self.text = text
        self.headers = {"Content-Type": content_type}


class _FakeHttp:
    """Offline stand-in for ssa.http.HttpClient: a feed plus per-URL pages."""

    def __init__(self, feed_text, pages):
        self.feed_text = feed_text
        self.pages = pages  # url -> _FakeResponse | Exception
        self.fetched = []  # body-fetch urls, in order

    def get_text(self, url, **kwargs):
        return self.feed_text

    def get(self, url, **kwargs):
        self.fetched.append(url)
        page = self.pages.get(url)
        if page is None:
            raise RuntimeError(f"unexpected fetch: {url}")
        if isinstance(page, Exception):
            raise page
        return page


def _http(pages):
    return _FakeHttp(load_fixture("biztoc.rss"), pages)


def _seen(tmp_path):
    return SeenState.load(str(tmp_path / "seen.json"))


# --- body extraction (pure) -------------------------------------------------
def test_extract_body_scopes_to_article_container():
    body = biztoc.extract_body(load_fixture("biztoc_page_container.html"))
    assert "hyperscaler capital expenditure" in body
    assert "networking segment" in body
    # paragraphs outside the article container are excluded
    assert "newsletter" not in body and "All rights reserved" not in body


def test_extract_body_falls_back_to_all_paragraphs():
    body = biztoc.extract_body(load_fixture("biztoc_page_paragraphs.html"))
    assert "Constellation Energy signed" in body
    assert "round-the-clock carbon-free" in body


def test_extract_body_container_without_paragraphs_uses_fallback():
    html = '<main><div>headline only</div></main><p>loose paragraph text</p>'
    assert biztoc.extract_body(html) == "loose paragraph text"


def test_extract_body_empty_page_returns_empty():
    assert biztoc.extract_body(load_fixture("biztoc_page_empty.html")) == ""


# --- firehose collection ----------------------------------------------------
def test_firehose_emits_full_text_records(tmp_path):
    http = _http({
        NVDA_URL: _FakeResponse(load_fixture("biztoc_page_container.html")),
        CEG_URL: _FakeResponse(load_fixture("biztoc_page_paragraphs.html")),
    })
    records = biztoc.collect_firehose(http, {}, _seen(tmp_path))

    assert len(records) == 2
    assert all(a.source == "biztoc" and a.source_type == "news" for a in records)
    nvda, ceg = records
    assert "hyperscaler capital expenditure" in nvda.summary_or_text
    assert nvda.raw["full_text"] is True
    assert nvda.published == "2026-06-23T12:05:00+00:00"  # RSS pubDate survives
    assert "round-the-clock carbon-free" in ceg.summary_or_text


def test_firehose_skips_seen_links_before_fetching(tmp_path):
    seen = _seen(tmp_path)
    seen.add(NVDA_URL, NVDA_TITLE)  # processed on a prior run
    http = _http({CEG_URL: _FakeResponse(load_fixture("biztoc_page_paragraphs.html"))})

    records = biztoc.collect_firehose(http, {}, seen)

    assert [a.url for a in records] == [CEG_URL]
    assert http.fetched == [CEG_URL]  # the seen link cost zero body fetches


def test_firehose_isolates_per_link_failures(tmp_path):
    http = _http({
        NVDA_URL: RuntimeError("403 Forbidden — bot blocked"),
        CEG_URL: _FakeResponse(load_fixture("biztoc_page_paragraphs.html")),
    })
    records = biztoc.collect_firehose(http, {}, _seen(tmp_path))

    assert len(records) == 2  # one blocked link must not kill the batch
    nvda, ceg = records
    # the failed fetch degrades to the RSS summary, and says so in raw
    assert nvda.summary_or_text == "Via Reuters: Nvidia shares rose to a record."
    assert nvda.raw["full_text"] is False
    assert ceg.raw["full_text"] is True


def test_firehose_empty_body_falls_back_to_summary(tmp_path):
    http = _http({
        NVDA_URL: _FakeResponse(load_fixture("biztoc_page_empty.html")),
        CEG_URL: _FakeResponse(load_fixture("biztoc_page_paragraphs.html")),
    })
    records = biztoc.collect_firehose(http, {}, _seen(tmp_path))
    assert records[0].summary_or_text == "Via Reuters: Nvidia shares rose to a record."
    assert records[0].raw["full_text"] is False


def test_firehose_skips_non_html_bodies(tmp_path):
    http = _http({
        NVDA_URL: _FakeResponse("%PDF-1.4 binary soup", content_type="application/pdf"),
        CEG_URL: _FakeResponse(load_fixture("biztoc_page_paragraphs.html")),
    })
    records = biztoc.collect_firehose(http, {}, _seen(tmp_path))
    assert records[0].raw["full_text"] is False  # PDFs are not souped
    assert records[0].summary_or_text == "Via Reuters: Nvidia shares rose to a record."


def test_firehose_max_articles_caps_fetches(tmp_path):
    http = _http({NVDA_URL: _FakeResponse(load_fixture("biztoc_page_container.html"))})
    records = biztoc.collect_firehose(
        http, {"BIZTOC_MAX_ARTICLES": 1}, _seen(tmp_path))
    assert len(records) == 1 and http.fetched == [NVDA_URL]


def test_firehose_truncates_long_bodies(tmp_path):
    http = _http({
        NVDA_URL: _FakeResponse(load_fixture("biztoc_page_container.html")),
        CEG_URL: _FakeResponse(load_fixture("biztoc_page_paragraphs.html")),
    })
    records = biztoc.collect_firehose(
        http, {"BIZTOC_MAX_BODY_CHARS": 40}, _seen(tmp_path))
    assert all(len(a.summary_or_text) <= 40 for a in records)
    assert all(a.raw["full_text"] for a in records)  # truncated, not dropped


def test_firehose_is_registered_first_class():
    assert sources.FIREHOSE is biztoc
