"""ssa.scrape — Phase-1 entrypoint.

Orchestrates: load config + watchlist + seen-state → run each source adapter
(failure-isolated) → dedup (cross-source + against prior runs) → append
``outputs/articles_<YYYY-MM-DD>.jsonl`` → persist ``state/seen.json``.

Run::

    python -m ssa.scrape            # full run (curated sources + biztoc firehose)
    python -m ssa.scrape --no-firehose
    python -m ssa.scrape --config config.json

Scope is Phase 1 ONLY: no ticker matching, scoring, or dashboard.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections import Counter
from dataclasses import dataclass

from . import sources
from .dedup import SeenState
from .http import HttpClient
from .record import Article, append_jsonl, today_utc

log = logging.getLogger("ssa.scrape")


@dataclass
class Paths:
    config: str
    output_dir: str
    articles_template: str
    seen_state: str
    watchlist: str

    def articles_path(self) -> str:
        return os.path.join(self.output_dir, self.articles_template.format(today_utc()))


def load_config(config_path: str) -> tuple[dict, Paths]:
    """Read config.json and build the effective ssa config.

    Reuses the legacy top-level keys (USER_AGENTS / REQUEST_DELAY / MAX_RETRIES)
    and merges the new ``SSA`` block on top. The legacy Ollama keys
    (MODEL / API_URL) are never read here.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    ssa_cfg = dict(raw.get("SSA", {}))
    # Reuse legacy top-level knobs unless the SSA block overrides them.
    for key in ("USER_AGENTS", "REQUEST_DELAY", "MAX_RETRIES"):
        ssa_cfg.setdefault(key, raw.get(key))

    paths = Paths(
        config=config_path,
        output_dir=ssa_cfg.get("OUTPUT_DIR", raw.get("OUTPUT_DIR", "outputs")),
        articles_template=ssa_cfg.get("ARTICLES_TEMPLATE", "articles_{}.jsonl"),
        seen_state=ssa_cfg.get("SEEN_STATE_FILE", "state/seen.json"),
        watchlist=ssa_cfg.get("WATCHLIST_FILE", "watchlist.json"),
    )
    return ssa_cfg, paths


def load_watchlist(path: str) -> list[str]:
    """Load ticker symbols from watchlist.json (drives Yahoo per-ticker RSS)."""
    if not os.path.exists(path):
        log.warning("watchlist %s missing — Yahoo per-ticker RSS will be empty.", path)
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read watchlist %s: %s", path, exc)
        return []
    tickers = data.get("tickers", []) if isinstance(data, dict) else list(data)
    cleaned = [str(t).strip().upper() for t in tickers if str(t).strip()]
    # the on-disk flag is "_PROVISIONAL"; accept either case
    if isinstance(data, dict) and (data.get("_provisional") or data.get("_PROVISIONAL")):
        log.warning(
            "watchlist.json is marked PROVISIONAL (%d tickers) — replace it with "
            "the real AI-buildout universe before trusting coverage.", len(cleaned),
        )
    return cleaned


def _collect(module, http, cfg, watchlist) -> list[Article]:
    """Run one adapter's collect() with failure isolation."""
    name = getattr(module, "SOURCE", module.__name__)
    try:
        records = module.collect(http, cfg, watchlist)
        log.info("adapter %-12s -> %d records", name, len(records))
        return records
    except Exception as exc:  # one dead feed must not abort the run
        log.warning("adapter %-12s FAILED: %s", name, exc)
        return []


def run(config_path: str = "config.json", use_firehose: bool = True) -> dict:
    cfg, paths = load_config(config_path)
    os.makedirs(paths.output_dir, exist_ok=True)
    os.makedirs(os.path.dirname(paths.seen_state) or ".", exist_ok=True)

    watchlist = load_watchlist(paths.watchlist)
    http = HttpClient(
        user_agents=cfg.get("USER_AGENTS"),
        request_delay=cfg.get("REQUEST_DELAY", 1) or 0,
        max_retries=cfg.get("MAX_RETRIES", 3) or 3,
    )
    seen = SeenState.load(paths.seen_state)

    # --- collect from primary adapters -----------------------------------
    candidates: list[Article] = []
    for module in sources.PRIMARY:
        candidates.extend(_collect(module, http, cfg, watchlist))

    # --- biztoc full-text firehose (Phase 1b — first-class, always on) ----
    # Gets the seen-state for pre-fetch dedup: links from PRIOR runs cost no
    # body fetch. Same-run overlap with the curated sources above still lands
    # here occasionally (they aren't in `seen` yet) and is dropped by the
    # post-collection dedup loop below — wasted fetch, correct output.
    if use_firehose:
        try:
            records = sources.FIREHOSE.collect_firehose(http, cfg, seen)
            log.info("adapter %-12s -> %d records (firehose)",
                     sources.FIREHOSE.SOURCE, len(records))
            candidates.extend(records)
        except Exception as exc:  # a blocked feed must not abort the run
            log.warning("adapter %-12s FAILED: %s", sources.FIREHOSE.SOURCE, exc)

    http.close()

    # --- dedup: cross-source (within run) + against prior runs ------------
    parsed_by_source = Counter(a.source for a in candidates)
    accepted: list[Article] = []
    for art in candidates:
        if seen.is_seen(art.url, art.title):
            continue
        seen.add(art.url, art.title)
        accepted.append(art)
    accepted_by_source = Counter(a.source for a in accepted)

    # --- persist: append JSONL, then atomically save seen-state ----------
    out_path = paths.articles_path()
    written = append_jsonl(out_path, accepted)
    seen.save()

    summary = {
        "output": out_path,
        "parsed_total": len(candidates),
        "accepted_total": len(accepted),
        "written": written,
        "duplicates_skipped": len(candidates) - len(accepted),
        "parsed_by_source": dict(parsed_by_source),
        "accepted_by_source": dict(accepted_by_source),
        "seen_state": paths.seen_state,
        "seen_urls": len(seen.urls),
        "watchlist_tickers": len(watchlist),
    }
    _print_summary(summary)
    return summary


def _print_summary(s: dict) -> None:
    line = "=" * 60
    print(f"\n{line}\nssa.scrape — Phase 1 run complete\n{line}")
    print(f"output file        : {s['output']}")
    print(f"records written    : {s['written']} "
          f"({s['accepted_total']} new, {s['duplicates_skipped']} dup-skipped, "
          f"{s['parsed_total']} parsed)")
    print(f"seen-state         : {s['seen_state']} ({s['seen_urls']} urls)")
    print(f"watchlist tickers  : {s['watchlist_tickers']}")
    all_sources = sorted(set(s["parsed_by_source"]) | set(s["accepted_by_source"]))
    print("\nper-source (parsed → new):")
    if not all_sources:
        print("  (no records parsed from any source)")
    for src in all_sources:
        p = s["parsed_by_source"].get(src, 0)
        a = s["accepted_by_source"].get(src, 0)
        print(f"  {src:18s} {p:4d} → {a:4d}")
    print(line)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ssa Phase-1 scraper")
    parser.add_argument("--config", default="config.json", help="path to config.json")
    parser.add_argument("--no-firehose", action="store_true",
                        help="skip the biztoc full-text firehose (curated sources only)")
    parser.add_argument("--quiet", action="store_true", help="warnings only")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    summary = run(config_path=args.config, use_firehose=not args.no_firehose)
    # Non-zero exit if literally nothing parsed — signals a broken environment.
    return 0 if summary["parsed_total"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
