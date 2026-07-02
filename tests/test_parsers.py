"""Parser tests: each adapter's pure parse_* against a saved fixture.

No live-endpoint calls — every payload comes from tests/fixtures/.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import load_fixture  # noqa: E402
from ssa.dedup import SeenState  # noqa: E402
from ssa.sources import apewisdom, biztoc, edgar, gdelt, sector_rss, yahoo_rss  # noqa: E402


# --- EDGAR ----------------------------------------------------------------
def test_edgar_parse_atom():
    arts = edgar.parse_atom(load_fixture("edgar_getcurrent.atom"))
    assert len(arts) == 2
    nvda = arts[0]
    assert nvda.source == "edgar"
    assert nvda.source_type == "filing"
    assert nvda.raw["cik"] == "0001045810"
    assert nvda.raw["form"] == "8-K"
    assert nvda.raw["accession"] == "0001045810-26-000087"
    assert nvda.published == "2026-06-23T15:58:00+00:00"  # -04:00 -> UTC
    assert nvda.url.startswith("https://sec.gov/cgi-bin/browse-edgar")
    assert arts[1].raw["form"] == "10-Q"


# --- Yahoo RSS ------------------------------------------------------------
def test_yahoo_parse_rss():
    arts = yahoo_rss.parse_rss(load_fixture("yahoo_nvda.rss"), "NVDA")
    assert len(arts) == 2
    first = arts[0]
    assert first.source == "yahoo-rss"
    assert first.source_type == "news"
    assert first.raw["ticker"] == "NVDA"
    # tracking params stripped during canonicalization
    assert "utm_source" not in first.url and ".tsrc" not in first.url
    assert first.published == "2026-06-23T12:00:00+00:00"


# --- GDELT (JSON, not RSS) ------------------------------------------------
def test_gdelt_parse_json_dict_and_string():
    raw = load_fixture("gdelt_doc.json")
    arts = gdelt.parse_json(json.loads(raw))
    assert len(arts) == 2
    assert arts[0].source == "gdelt"
    assert arts[0].source_type == "news"
    assert arts[0].published == "2026-06-23T12:00:00+00:00"  # compact seendate
    assert arts[0].raw["domain"] == "example-news.com"
    # also accepts a raw JSON string
    assert len(gdelt.parse_json(raw)) == 2


# --- Sector RSS -----------------------------------------------------------
def test_sector_parse_rss_tags_source():
    arts = sector_rss.parse_rss(load_fixture("sector_dcd.rss"), "dcd-rss")
    assert len(arts) == 2
    assert all(a.source == "dcd-rss" for a in arts)
    assert all(a.source_type == "news" for a in arts)


def test_sector_parse_rejects_unknown_source():
    try:
        sector_rss.parse_rss(load_fixture("sector_dcd.rss"), "not-a-real-source")
        assert False, "expected ValueError"
    except ValueError:
        pass


# --- ApeWisdom (social, mention counts) -----------------------------------
def test_apewisdom_parse_json():
    data = json.loads(load_fixture("apewisdom.json"))
    arts = apewisdom.parse_json(data, snapshot_date="2026-06-23", top_n=50)
    assert len(arts) == 3
    nvda = arts[0]
    assert nvda.source == "apewisdom"
    assert nvda.source_type == "social"
    assert nvda.raw["mentions"] == 320
    assert nvda.raw["ticker"] == "NVDA"
    assert nvda.published is None
    # snapshot baked into url so daily snapshots stay distinct
    assert "snapshot=2026-06-23" in nvda.url


def test_apewisdom_top_n_caps():
    data = json.loads(load_fixture("apewisdom.json"))
    arts = apewisdom.parse_json(data, snapshot_date="2026-06-23", top_n=2)
    assert len(arts) == 2


def test_apewisdom_snapshot_makes_days_distinct():
    data = json.loads(load_fixture("apewisdom.json"))
    day1 = apewisdom.parse_json(data, snapshot_date="2026-06-23", top_n=1)[0]
    day2 = apewisdom.parse_json(data, snapshot_date="2026-06-24", top_n=1)[0]
    assert day1.id != day2.id  # same ticker, different day -> distinct record


# --- biztoc ---------------------------------------------------------------
def test_biztoc_parse_rss():
    arts = biztoc.parse_rss(load_fixture("biztoc.rss"))
    assert len(arts) == 2
    assert all(a.source == "biztoc" for a in arts)


# --- cross-source dedup integration (fixtures only) -----------------------
def test_cross_source_collapse_yahoo_and_biztoc(tmp_path):
    """The same wire story from Yahoo (with '- Reuters' suffix) and biztoc
    (no suffix, different url) must collapse to ONE via the title hash."""
    yahoo = yahoo_rss.parse_rss(load_fixture("yahoo_nvda.rss"), "NVDA")
    btoc = biztoc.parse_rss(load_fixture("biztoc.rss"))

    seen = SeenState.load(str(tmp_path / "seen.json"))
    accepted = []
    for art in [*yahoo, *btoc]:
        if seen.is_seen(art.url, art.title):
            continue
        seen.add(art.url, art.title)
        accepted.append(art)

    titles = [a.title for a in accepted]
    # The Nvidia story appears in both feeds but should be accepted only once.
    nvidia_like = [t for t in titles if t.lower().startswith("nvidia hits record")]
    assert len(nvidia_like) == 1
    # The other distinct stories survive (AMD from yahoo, Constellation from biztoc).
    assert any("amd" in t.lower() for t in titles)
    assert any("constellation" in t.lower() for t in titles)


def test_second_pass_is_idempotent(tmp_path):
    """Re-running the same parsed records adds nothing new (seen-state)."""
    arts = gdelt.parse_json(json.loads(load_fixture("gdelt_doc.json")))
    seen = SeenState.load(str(tmp_path / "seen.json"))
    first = [a for a in arts if not _accept(seen, a)]
    # everything accepted on the first pass
    assert len(first) == len(arts)
    # second pass: nothing new
    second = [a for a in arts if not _accept(seen, a)]
    assert second == []


def _accept(seen, art):
    """Helper: return True if already seen, else record it and return False."""
    if seen.is_seen(art.url, art.title):
        return True
    seen.add(art.url, art.title)
    return False
