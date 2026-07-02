"""Phase-2 extraction schema — PINNED (version 1).

The per-article contract the triage engine must return. Changing any field,
enum, or range is a SCHEMA BUMP: bump ``TRIAGE_SCHEMA_VERSION``, document why,
and expect old triage_*.jsonl records to be non-comparable (a re-triage at
volume costs real money — this is the expensive-to-reverse decision PLAN says
to pin with the user first).

Three artifacts stay in lockstep here:
  * ``RESPONSE_SCHEMA`` — the Gemini structured-output schema (API-enforced).
  * ``validate_extraction`` — local validation (ranges/enums the API subset
    can't fully express). The engine retries once on failure.
  * ``build_prompt`` — the instruction text.
"""

from __future__ import annotations

TRIAGE_SCHEMA_VERSION = 1

EVENT_TYPES = ["capex", "earnings", "product", "policy", "supply", "rating", "other"]
DIRECTIONS = ["bull", "bear", "neutral"]

# Keys the model must return (the triage record adds id/url/provenance on top).
EXTRACTION_KEYS = [
    "tickers", "entities", "event_type", "sentiment",
    "signal_tags", "key_figures", "confidence", "escalate",
]

# Gemini structured-output schema (OpenAPI subset, UPPERCASE types).
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "tickers": {"type": "ARRAY", "items": {"type": "STRING"}},
        "entities": {"type": "ARRAY", "items": {"type": "STRING"}},
        "event_type": {"type": "STRING", "enum": EVENT_TYPES},
        "sentiment": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "ticker": {"type": "STRING"},
                    "score": {"type": "INTEGER"},
                    "direction": {"type": "STRING", "enum": DIRECTIONS},
                },
                "required": ["ticker", "score", "direction"],
            },
        },
        "signal_tags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "key_figures": {"type": "STRING"},
        "confidence": {"type": "NUMBER"},
        "escalate": {"type": "BOOLEAN"},
    },
    "required": EXTRACTION_KEYS,
    "propertyOrdering": EXTRACTION_KEYS,
}

_PROMPT = """\
You are the triage pass of a stock-sentiment pipeline for an AI-buildout
investment strategy (AI semiconductors + datacenter power/grid/cooling).
Read ONE news item and extract structured signals as JSON per the schema.

Rules:
- tickers: primary exchange tickers (e.g. NVDA, TSM) of companies MATERIALLY
  discussed — [] if none. Never invent tickers for private companies.
- entities: organizations materially involved.
- event_type: capex|earnings|product|policy|supply|rating|other.
- sentiment: EXACTLY one entry per ticker in `tickers`; score 0-100
  (0=strong sell, 50=neutral, 100=strong buy), direction consistent with score.
- signal_tags: short kebab-case tags, e.g. hyperscaler-capex, backlog,
  guidance-raise, supply-constraint, power-deal, new-product, policy, ai-demand.
- key_figures: the concrete numbers of the story in one line ("" if none).
- confidence: 0.0-1.0 — your confidence in THIS extraction.
- escalate: true ONLY if market-moving / high-signal (large capex or contract,
  guidance change, major policy or supply shock) OR important-but-uncertain
  (low confidence on a story that looks significant).

Watchlist context — the strategy universe (extract ALL relevant tickers, not
only these): {watchlist}

ITEM
source: {source} ({source_type}) | published: {published}
title: {title}
text: {text}
"""


def build_prompt(article: dict, watchlist: list[str], max_chars: int = 12000) -> str:
    """Render the triage prompt for one article record (dict from JSONL)."""
    text = (article.get("summary_or_text") or "").strip()
    if len(text) > max_chars:
        text = text[:max_chars] + " …[truncated]"
    return _PROMPT.format(
        watchlist=", ".join(watchlist) if watchlist else "(none provided)",
        source=article.get("source", "?"),
        source_type=article.get("source_type", "?"),
        published=article.get("published") or "unknown",
        title=article.get("title", ""),
        text=text or "(headline only)",
    )


def normalize_extraction(obj: dict) -> dict:
    """Tidy an extraction in place: upper-case/strip tickers, dedupe, strip strings."""
    if isinstance(obj.get("tickers"), list):
        seen, tickers = set(), []
        for t in obj["tickers"]:
            t = str(t).strip().upper()
            if t and t not in seen:
                seen.add(t)
                tickers.append(t)
        obj["tickers"] = tickers
    if isinstance(obj.get("sentiment"), list):
        for s in obj["sentiment"]:
            if isinstance(s, dict) and "ticker" in s:
                s["ticker"] = str(s["ticker"]).strip().upper()
    if isinstance(obj.get("entities"), list):
        obj["entities"] = [str(e).strip() for e in obj["entities"] if str(e).strip()]
    if isinstance(obj.get("signal_tags"), list):
        obj["signal_tags"] = [str(t).strip() for t in obj["signal_tags"] if str(t).strip()]
    return obj


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate_extraction(obj) -> list[str]:
    """Return a list of violations (empty = valid). Local source of truth for
    ranges/enums; stricter than what the API-side schema subset enforces."""
    if not isinstance(obj, dict):
        return ["extraction is not a JSON object"]
    errors = [f"missing key: {k}" for k in EXTRACTION_KEYS if k not in obj]
    if errors:
        return errors

    for key in ("tickers", "entities", "signal_tags"):
        val = obj[key]
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            errors.append(f"{key} must be a list of strings")

    if obj["event_type"] not in EVENT_TYPES:
        errors.append(f"event_type {obj['event_type']!r} not in {EVENT_TYPES}")

    if not isinstance(obj["sentiment"], list):
        errors.append("sentiment must be a list")
    else:
        for i, s in enumerate(obj["sentiment"]):
            if not isinstance(s, dict):
                errors.append(f"sentiment[{i}] must be an object")
                continue
            if not isinstance(s.get("ticker"), str) or not s.get("ticker").strip():
                errors.append(f"sentiment[{i}].ticker must be a non-empty string")
            if not _is_num(s.get("score")) or not (0 <= s["score"] <= 100):
                errors.append(f"sentiment[{i}].score must be a number in 0-100")
            if s.get("direction") not in DIRECTIONS:
                errors.append(f"sentiment[{i}].direction must be one of {DIRECTIONS}")

    if not isinstance(obj["key_figures"], str):
        errors.append("key_figures must be a string")
    if not _is_num(obj["confidence"]) or not (0.0 <= obj["confidence"] <= 1.0):
        errors.append("confidence must be a number in 0.0-1.0")
    if not isinstance(obj["escalate"], bool):
        errors.append("escalate must be a boolean")
    return errors
