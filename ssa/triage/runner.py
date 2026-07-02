"""Phase-2 triage runner: enrich every article record with cheap LLM signals.

Reads ``outputs/articles_*.jsonl`` (curated + firehose), skips ids already in
any ``outputs/triage_*.jsonl`` (idempotent re-runs, mirroring seen-state), and
appends enriched records to ``outputs/triage_<today>.jsonl``.

Guardrails (PLAN): bounded concurrency, a hard per-run USD spend cap computed
from usage metadata, structured-output validation with one retry, per-article
failure isolation (failed ids are NOT recorded, so the next run retries them),
and ``valid_tickers.txt`` as a hallucination ALLOWLIST — never the matcher.
"""

from __future__ import annotations

import glob
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from ..record import now_utc_iso, today_utc
from ..scrape import load_config, load_watchlist
from .engine import GeminiEngine, TriageError, Usage, load_api_key
from .schema import EXTRACTION_KEYS, TRIAGE_SCHEMA_VERSION, build_prompt

log = logging.getLogger("ssa.triage")

# Rough dry-run estimate constants (chars-per-token, fixed prompt overhead,
# expected output+thought tokens per article). Estimates only — real spend is
# metered from usageMetadata.
_CHARS_PER_TOKEN = 4
_PROMPT_OVERHEAD_TOKENS = 450
_EST_OUTPUT_TOKENS = 600


def _load_articles(pattern: str) -> list[dict]:
    """All article records matching the glob, deduped by id (first wins)."""
    articles: list[dict] = []
    seen_ids: set[str] = set()
    for path in sorted(glob.glob(pattern)):
        with open(path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("skipping bad JSONL line %s:%d", path, lineno)
                    continue
                rid = rec.get("id")
                if not rid or rid in seen_ids:
                    continue
                seen_ids.add(rid)
                articles.append(rec)
    return articles


def _load_triaged_ids(output_dir: str) -> set[str]:
    """Ids already triaged, derived from the triage outputs themselves (no
    second state file to drift)."""
    ids: set[str] = set()
    for path in glob.glob(os.path.join(output_dir, "triage_*.jsonl")):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rid = json.loads(line).get("id")
                except json.JSONDecodeError:
                    continue
                if rid:
                    ids.add(rid)
    return ids


def _load_allowlist(path: str) -> set[str] | None:
    """valid_tickers.txt as a set, or None (=> no filtering) if unreadable."""
    if not os.path.exists(path):
        log.warning("ticker allowlist %s missing — hallucination filter OFF.", path)
        return None
    with open(path, "r", encoding="utf-8") as f:
        return {line.strip().upper() for line in f if line.strip()}


def _apply_allowlist(extraction: dict, allowlist: set[str] | None) -> tuple[dict, list[str]]:
    """Drop tickers (and their sentiment rows) not present in the allowlist."""
    if not allowlist:
        return extraction, []
    rejected = [t for t in extraction["tickers"] if t not in allowlist]
    if rejected:
        extraction["tickers"] = [t for t in extraction["tickers"] if t in allowlist]
        extraction["sentiment"] = [
            s for s in extraction["sentiment"] if s.get("ticker") in allowlist
        ]
    return extraction, rejected


def _append_dicts(path: str, records: list[dict]) -> None:
    if not records:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def run(
    config_path: str = "config.json",
    limit: int = 0,
    dry_run: bool = False,
    input_glob: str | None = None,
    engine=None,
) -> dict:
    cfg, paths = load_config(config_path)
    output_dir = paths.output_dir
    pattern = input_glob or os.path.join(output_dir, "articles_*.jsonl")

    articles = _load_articles(pattern)
    triaged_ids = _load_triaged_ids(output_dir)
    todo = [a for a in articles if a["id"] not in triaged_ids]
    already_triaged = len(articles) - len(todo)
    if limit:
        todo = todo[:limit]

    max_chars = int(cfg.get("TRIAGE_MAX_INPUT_CHARS", 12000))
    price_in = float(cfg.get("TRIAGE_PRICE_IN_PER_1M", 0.25))
    price_out = float(cfg.get("TRIAGE_PRICE_OUT_PER_1M", 1.50))
    model = cfg.get("TRIAGE_MODEL", "gemini-3.1-flash-lite")

    summary = {
        "output": os.path.join(
            output_dir, cfg.get("TRIAGE_TEMPLATE", "triage_{}.jsonl").format(today_utc())),
        "model": model,
        "articles_found": len(articles),
        "already_triaged": already_triaged,
        "todo": len(todo),
        "triaged": 0, "failed": 0, "escalated": 0,
        "prompt_tokens": 0, "output_tokens": 0, "thought_tokens": 0,
        "cost_usd": 0.0, "capped": False, "dry_run": dry_run,
    }

    if dry_run:
        est_in = sum(
            _PROMPT_OVERHEAD_TOKENS
            + min(len(a.get("summary_or_text") or ""), max_chars) // _CHARS_PER_TOKEN
            for a in todo
        )
        est_out = len(todo) * _EST_OUTPUT_TOKENS
        summary["est_prompt_tokens"] = est_in
        summary["est_output_tokens"] = est_out
        summary["est_cost_usd"] = round(
            (est_in * price_in + est_out * price_out) / 1_000_000, 4)
        _print_summary(summary)
        return summary

    if engine is None:
        api_key = load_api_key()
        if not api_key:
            raise TriageError(
                "GOOGLE_API_KEY not found (env var or .env) — cannot start the "
                "paid triage engine.")
        engine = GeminiEngine(
            api_key,
            model,
            max_retries=int(cfg.get("MAX_RETRIES", 3) or 3),
            max_output_tokens=int(cfg.get("TRIAGE_MAX_OUTPUT_TOKENS", 2048)),
        )

    watchlist = load_watchlist(paths.watchlist)
    allowlist = _load_allowlist(cfg.get("TRIAGE_ALLOWLIST_FILE", "valid_tickers.txt"))
    spend_cap = float(cfg.get("TRIAGE_SPEND_CAP_USD", 0.50))
    workers = max(1, int(cfg.get("TRIAGE_MAX_WORKERS", 4)))

    def _one(article: dict):
        try:
            extraction, usage, retries = engine.extract(
                build_prompt(article, watchlist, max_chars))
            return extraction, usage, retries, None
        except Exception as exc:  # failure isolation — retried next run
            return None, None, 0, str(exc)

    total_usage = Usage()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for start in range(0, len(todo), workers):
            if summary["cost_usd"] >= spend_cap:
                summary["capped"] = True
                log.warning(
                    "spend cap $%.2f reached after %d articles — stopping "
                    "(%d left; raise TRIAGE_SPEND_CAP_USD to continue).",
                    spend_cap, summary["triaged"], len(todo) - start)
                break
            batch = todo[start:start + workers]
            records: list[dict] = []
            for article, (extraction, usage, retries, err) in zip(batch, ex.map(_one, batch)):
                if err is not None:
                    summary["failed"] += 1
                    log.warning("triage FAILED %s (%s): %s",
                                article["id"][:12], article.get("source"), err)
                    continue
                extraction, rejected = _apply_allowlist(extraction, allowlist)
                cost = usage.cost_usd(price_in, price_out)
                total_usage = total_usage + usage
                summary["cost_usd"] += cost
                summary["triaged"] += 1
                summary["escalated"] += 1 if extraction["escalate"] else 0
                records.append({
                    "id": article["id"],
                    "url": article.get("url"),
                    "title": article.get("title"),
                    "source": article.get("source"),
                    "source_type": article.get("source_type"),
                    "published": article.get("published"),
                    "schema_version": TRIAGE_SCHEMA_VERSION,
                    **{k: extraction[k] for k in EXTRACTION_KEYS},
                    "tickers_rejected": rejected,
                    "triage": {
                        "engine": engine.name, "model": engine.model,
                        "at": now_utc_iso(),
                        "prompt_tokens": usage.prompt_tokens,
                        "output_tokens": usage.output_tokens,
                        "thought_tokens": usage.thought_tokens,
                        "cost_usd": round(cost, 6), "retries": retries,
                    },
                })
            _append_dicts(summary["output"], records)  # per-batch: crash-safe

    summary["prompt_tokens"] = total_usage.prompt_tokens
    summary["output_tokens"] = total_usage.output_tokens
    summary["thought_tokens"] = total_usage.thought_tokens
    summary["cost_usd"] = round(summary["cost_usd"], 4)
    _print_summary(summary)
    return summary


def _print_summary(s: dict) -> None:
    line = "=" * 60
    mode = "DRY RUN (no API calls)" if s["dry_run"] else f"model {s['model']}"
    print(f"\n{line}\nssa.triage — Phase 2 {mode}\n{line}")
    print(f"articles found     : {s['articles_found']} "
          f"({s['already_triaged']} already triaged, {s['todo']} to do)")
    if s["dry_run"]:
        print(f"estimated tokens   : ~{s['est_prompt_tokens']} in / ~{s['est_output_tokens']} out")
        print(f"estimated cost     : ~${s['est_cost_usd']:.4f}")
    else:
        print(f"triaged            : {s['triaged']} "
              f"({s['failed']} failed, {s['escalated']} escalated)")
        print(f"tokens             : {s['prompt_tokens']} in / {s['output_tokens']} out "
              f"/ {s['thought_tokens']} thought")
        print(f"metered cost       : ${s['cost_usd']:.4f}"
              + ("  ** SPEND CAP HIT **" if s["capped"] else ""))
        print(f"output             : {s['output']}")
    print(line)
