"""Dedup tests: URL canonicalization, title normalization, seen-state."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ssa.dedup import (  # noqa: E402
    SeenState,
    canonicalize_url,
    make_id,
    normalize_title,
    title_hash,
)


# --- URL canonicalization -------------------------------------------------
def test_canonicalize_strips_tracking_params():
    a = canonicalize_url("https://finance.yahoo.com/news/x-123.html?utm_source=rss&utm_medium=feed&.tsrc=fin&id=42")
    # tracking params dropped, real param kept
    assert "utm_source" not in a
    assert "utm_medium" not in a
    assert ".tsrc" not in a
    assert "id=42" in a


def test_canonicalize_drops_fragment_and_www_and_case():
    a = canonicalize_url("HTTPS://WWW.Example.com/Path/#section")
    assert a == "https://example.com/Path"


def test_canonicalize_trailing_slash_and_param_sort():
    a = canonicalize_url("https://example.com/a/?b=2&a=1")
    b = canonicalize_url("https://www.example.com/a?a=1&b=2")
    assert a == b  # trailing slash + www + param order all normalized


def test_canonicalize_keeps_distinct_paths_distinct():
    assert canonicalize_url("https://x.com/a") != canonicalize_url("https://x.com/b")


def test_canonicalize_handles_empty():
    assert canonicalize_url("") == ""


# --- Title normalization --------------------------------------------------
def test_normalize_strips_publisher_suffix():
    assert normalize_title("Nvidia hits record - Reuters") == "nvidia hits record"
    assert normalize_title("Big news | Bloomberg") == "big news"
    assert normalize_title("AMD soars — CNBC") == "amd soars"


def test_normalize_does_not_strip_nonpublisher_tail():
    # "Q2" tail is not a known publisher; keep it.
    assert normalize_title("Earnings - Q2 beat") == "earnings q2 beat"


def test_normalize_smart_quotes_and_whitespace_and_case():
    assert normalize_title("  “Buy” the   DIP’s  ") == "buy the dip s"


def test_normalize_drops_emoji():
    assert normalize_title("Stocks rip higher 🚀🚀") == "stocks rip higher"


# --- id formula -----------------------------------------------------------
def test_make_id_is_sha1_of_canon_and_norm():
    import hashlib
    url = "https://www.example.com/a/?utm_source=x"
    title = "Foo Bar - Reuters"
    expected = hashlib.sha1(
        f"{canonicalize_url(url)}|{normalize_title(title)}".encode("utf-8")
    ).hexdigest()
    assert make_id(url, title) == expected
    assert len(make_id(url, title)) == 40


def test_same_story_diff_tracking_same_id():
    # Same wire story, one with tracking params, one without → same id.
    id1 = make_id("https://site.com/story?utm_source=a", "Headline - Reuters")
    id2 = make_id("https://www.site.com/story/", "Headline")
    assert id1 == id2


# --- SeenState ------------------------------------------------------------
def test_seenstate_roundtrip_and_idempotent(tmp_path):
    path = str(tmp_path / "seen.json")
    s = SeenState.load(path)
    assert not s.is_seen("https://x.com/a", "Title A")
    s.add("https://x.com/a", "Title A")
    s.save()

    s2 = SeenState.load(path)
    assert s2.is_seen("https://x.com/a", "Title A")
    # Re-adding the same is a no-op (idempotent).
    before = len(s2.urls)
    s2.add("https://x.com/a", "Title A")
    assert len(s2.urls) == before


def test_seenstate_cross_source_collapse_via_title(tmp_path):
    # Same story, DIFFERENT urls, same normalized title → second is "seen".
    path = str(tmp_path / "seen.json")
    s = SeenState.load(path)
    s.add("https://finance.yahoo.com/news/nvidia-record-123.html",
          "Nvidia hits record as data center demand surges - Reuters")
    # biztoc carries the same story under a different url + no publisher suffix
    assert s.is_seen("https://biztoc.com/x/abc123",
                     "Nvidia hits record as data center demand surges")


def test_seenstate_collapse_via_url(tmp_path):
    # Same url (one with tracking) but unrelated/edited title still collapses on url.
    path = str(tmp_path / "seen.json")
    s = SeenState.load(path)
    s.add("https://site.com/story?utm_source=a", "Original headline")
    assert s.is_seen("https://www.site.com/story/", "Edited headline text")


def test_seenstate_distinct_stories_not_collapsed(tmp_path):
    path = str(tmp_path / "seen.json")
    s = SeenState.load(path)
    s.add("https://a.com/one", "Completely different story one")
    assert not s.is_seen("https://b.com/two", "Another totally separate story two")
