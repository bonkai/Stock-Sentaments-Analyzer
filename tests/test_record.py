"""Record tests: pinned schema, id formula, date parsing, JSONL writer."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ssa.dedup import make_id  # noqa: E402
from ssa.record import append_jsonl, build_article, parse_date  # noqa: E402

PINNED_FIELDS = {
    "id", "source", "source_type", "url", "title",
    "published", "fetched_at", "summary_or_text", "raw",
}


def test_build_article_has_exactly_pinned_schema():
    art = build_article(
        source="gdelt", source_type="news",
        url="https://x.com/a", title="Hello", summary_or_text="body",
        published="2026-06-23T12:00:00Z", raw={"domain": "x.com"},
    )
    d = art.to_dict()
    assert set(d.keys()) == PINNED_FIELDS
    # Phase 1 must NOT leak ticker/sentiment fields.
    assert "ticker" not in d and "tickers" not in d
    assert "sentiment" not in d and "score" not in d


def test_id_matches_formula_and_url_is_canonical():
    art = build_article(
        source="yahoo-rss", source_type="news",
        url="https://www.x.com/a/?utm_source=z", title="Foo - Reuters",
    )
    assert art.id == make_id("https://www.x.com/a/?utm_source=z", "Foo - Reuters")
    # stored url is canonicalized (www + tracking stripped, trailing slash gone)
    assert art.url == "https://x.com/a"
    # title preserved as display string
    assert art.title == "Foo - Reuters"


def test_invalid_source_rejected():
    with pytest.raises(ValueError):
        build_article(source="nope", source_type="news", url="https://x.com", title="t")


def test_invalid_source_type_rejected():
    with pytest.raises(ValueError):
        build_article(source="gdelt", source_type="rumor", url="https://x.com", title="t")


# --- date parsing ---------------------------------------------------------
def test_parse_date_rfc822():
    assert parse_date("Tue, 23 Jun 2026 12:00:00 GMT") == "2026-06-23T12:00:00+00:00"


def test_parse_date_iso_with_z():
    assert parse_date("2026-06-23T12:00:00Z") == "2026-06-23T12:00:00+00:00"


def test_parse_date_gdelt_compact():
    assert parse_date("20260623T120000Z") == "2026-06-23T12:00:00+00:00"


def test_parse_date_offset_normalized_to_utc():
    assert parse_date("2026-06-23T08:00:00-04:00") == "2026-06-23T12:00:00+00:00"


def test_parse_date_none_and_garbage():
    assert parse_date(None) is None
    assert parse_date("") is None
    assert parse_date("not a date") is None


# --- JSONL writer ---------------------------------------------------------
def test_append_jsonl_writes_one_record_per_line(tmp_path):
    path = str(tmp_path / "out" / "articles_2026-06-23.jsonl")
    arts = [
        build_article(source="gdelt", source_type="news",
                      url="https://x.com/a", title="A"),
        build_article(source="gdelt", source_type="news",
                      url="https://x.com/b", title="B"),
    ]
    n = append_jsonl(path, arts)
    assert n == 2
    with open(path, encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    assert len(lines) == 2
    assert {l["title"] for l in lines} == {"A", "B"}
    # append, not overwrite
    append_jsonl(path, [build_article(source="gdelt", source_type="news",
                                      url="https://x.com/c", title="C")])
    with open(path, encoding="utf-8") as f:
        assert sum(1 for line in f if line.strip()) == 3


def test_append_jsonl_empty_is_noop(tmp_path):
    path = str(tmp_path / "articles.jsonl")
    assert append_jsonl(path, []) == 0
    assert not os.path.exists(path)
