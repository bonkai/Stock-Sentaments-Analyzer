"""Source adapters.

Each adapter exposes a uniform entrypoint::

    collect(http, cfg, watchlist) -> list[Article]

and keeps its pure parser (``parse_*``) separate from the network ``collect`` so
tests can exercise parsing against saved fixtures with zero live calls.

The orchestrator (``ssa.scrape``) runs each adapter inside its own try/except so
one dead feed never aborts the run (per-source failure isolation).
"""

from . import apewisdom, biztoc, edgar, gdelt, sector_rss, yahoo_rss

# Order matters: curated news/filing/social adapters run first; biztoc is the
# full-text FIREHOSE (Phase 1b) with its own entrypoint (collect_firehose —
# it needs the seen-state for pre-fetch dedup), so it is intentionally NOT in
# this primary list.
PRIMARY = [edgar, yahoo_rss, gdelt, sector_rss, apewisdom]
FIREHOSE = biztoc

__all__ = ["edgar", "yahoo_rss", "gdelt", "sector_rss", "apewisdom", "biztoc",
           "PRIMARY", "FIREHOSE"]
