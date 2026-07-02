"""Orchestrator helpers: watchlist loading."""

import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ssa.scrape import load_watchlist  # noqa: E402


def test_load_watchlist_reads_tickers(tmp_path):
    path = tmp_path / "watchlist.json"
    path.write_text(json.dumps({"tickers": ["nvda", " ceg ", ""]}))
    assert load_watchlist(str(path)) == ["NVDA", "CEG"]


def test_load_watchlist_warns_on_provisional_flag(tmp_path, caplog):
    """The real file uses upper-case "_PROVISIONAL" — the warning must fire."""
    path = tmp_path / "watchlist.json"
    path.write_text(json.dumps({"_PROVISIONAL": True, "tickers": ["NVDA"]}))
    with caplog.at_level(logging.WARNING, logger="ssa.scrape"):
        load_watchlist(str(path))
    assert any("PROVISIONAL" in r.message for r in caplog.records)


def test_load_watchlist_missing_file_is_empty(tmp_path):
    assert load_watchlist(str(tmp_path / "nope.json")) == []
