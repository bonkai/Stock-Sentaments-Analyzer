# Stock Sentiment Analyzer — Plan (v2)

*Updated: 2026-06-23 — Phase 1 shipped; added the cheap-triage firehose path.*
*Goal: Track and score news/social sentiment for the AI-buildout universe (AI semis + datacenter power/grid/cooling), so sentiment trends per ticker/sector are easy to see and act on.*

> **This file is the source of truth.** It supersedes `CLAUDE.md`, `memory/`, and `knowledge/`,
> which still describe the LEGACY Ollama pipeline at the repo root. Build fresh in `ssa/`.

---

## Architecture (v2 — two-bucket: cheap/wide + quality/narrow)

```
                          ┌─ curated: EDGAR · Yahoo RSS · GDELT · sector RSS · ApeWisdom   (Phase 1 ✅)
 sources ──▶ scrape ──────┤
                          └─ biztoc FIREHOSE — full text of ALL unread links   ← revived "old way" (Phase 1b)
                                   │
                                   ▼
                 Phase 2 · TRIAGE & EXTRACT   (CHEAP, WIDE — over ALL articles)
                     hosted Gemini Flash-Lite-class API
                     → tickers · entities · event type · quick sentiment · signal tags · escalate?
                                   │
                     ┌─────────────┴─────────────┐
                     ▼                           ▼
            low-signal: keep triage      Phase 3 · DEEP SCORING (QUALITY, NARROW)
            score as-is                   selectable claude | codex — iTerm2 tab, $0 subscription
                                          → careful per-ticker sentiment + rationale + tags
                                   │
                                   ▼
                       outputs/*.jsonl ──▶ Phase 4 · static HTML dashboard
```

**Two engines on purpose:** a hosted **Flash-Lite** model triages *everything* cheaply and wide;
the **claude/codex** dispatcher deep-scores *only what triage escalates*. The firehose gives breadth,
the curated sources + escalation give quality.

---

## Milestones (corrected — earlier "Done" marks were wrong)

| Milestone | Status |
|-----------|--------|
| Forge re-scaffold | Done |
| Pivot to AI-buildout thesis | Done (thesis *doc* still missing — see below) |
| ⚠️ Archive old stack to `legacy/` | **NOT DONE** — legacy Ollama stack still lives at the repo root |
| ⚠️ Thesis + watchlist captured | **PARTIAL** — `watchlist.json` is PROVISIONAL; `memory/ai-buildout-investment-thesis.md` is MISSING |
| **Phase 1 — Scraper** | ✅ **DONE** — `ssa/` package, 37 fixture tests, live-verified |
| **Phase 1b — biztoc full-text firehose** | ✅ **DONE** (2026-07-02) — `collect_firehose` in `ssa/sources/biztoc.py`, always-on (`--no-firehose` to skip); 12 fixture tests (suite: 49) |
| **Phase 2 — Triage & Extract** (Flash-Lite, all articles) | Not started ← **NEXT** |
| **Phase 3 — Deep Scoring** (claude/codex, escalated only) | Not started |
| **Phase 4 — Dashboard** | Not started |

---

## Phase 1 — Scraper ✅ (shipped 2026-06-23)

`python -m ssa.scrape` → fetch locked zero-key sources → dedup → `outputs/articles_<date>.jsonl`.
- Package `ssa/`: `scrape.py` (orchestrator), `record.py` (pinned schema + JSONL), `dedup.py`
  (canonical-URL + normalized-title, versioned), `http.py` (retry/UA), `sources/*.py` (6 adapters).
- Dedup state `state/seen.json` (replaces `processed_urls.txt`). Cross-source collapse on URL **or** title hash.
- Verified live: EDGAR, Yahoo RSS, GDELT, 3× sector RSS, ApeWisdom all yield records; idempotent re-runs; 0 dup ids.

## Phase 1b — biztoc full-text firehose ✅ (shipped 2026-07-02, the revived "old way")

Bring back the legacy `get_links.py` behaviour as a first-class deep source:
- Harvest **all latest biztoc links not already in `state/seen.json`** (the "unread" set).
- Fetch **full article text** for each (reuse legacy BeautifulSoup extraction; reuse `ssa/http.py`
  robots/UA-rotation/retry/politeness).
- Emit normal article records (`source=biztoc`, `source_type=news`) with `summary_or_text` = full body.
- Still deduped via `seen.json`. This is the WIDE firehose the triage pass feeds on.
- Heavy deps (bs4) live ONLY in this adapter — keep the rest of `ssa/` RSS/API-light.

*Shipped notes:* link index is the **RSS feed** (bounded + titled), not the legacy homepage
`<a>`-scrape (untitled nav/junk links). Per-link fetch failures / empty or non-HTML bodies degrade
to the RSS summary — `raw.full_text` flags real bodies so yield is measurable before Phase 2 pays
to triage. Bodies truncated at `BIZTOC_MAX_BODY_CHARS` (20k); optional `BIZTOC_MAX_ARTICLES` cap
(0 = uncapped, capping is logged). Note: neither `ssa/http.py` nor the legacy article path ever did
**robots.txt** checks — that claim above was aspirational; add it deliberately if wanted.

## Phase 2 — Triage & Extract  ← NEXT  (cheap, wide)

- **Engine:** hosted **Gemini Flash-Lite-class** API — cheapest per token, scales to "all articles".
  Pluggable behind an engine interface. Key from `GOOGLE_API_KEY` **env var** — never committed; gitignore the key.
  ⚠️ This deliberately relaxes the original "$0 / no hosted API" rule for the firehose bucket (cost is pennies/1000s of articles).
- **Runs over ALL article records** (curated + firehose). Absorbs the old "match" phase — the LLM extracts
  tickers/sectors/entities instead of regex. `valid_tickers.txt` becomes a **hallucination allowlist**, not the matcher.
- **Per-article extraction (pin this schema at phase start), e.g.:**
  ```json
  { "id": "<article id>", "tickers": ["NVDA"], "entities": ["Nvidia","TSMC"],
    "event_type": "capex|earnings|product|policy|supply|rating|other",
    "sentiment": [{"ticker":"NVDA","score":0-100,"direction":"bull|bear|neutral"}],
    "signal_tags": ["hyperscaler-capex","backlog","policy",...],
    "key_figures": "...", "confidence": 0.0-1.0, "escalate": true }
  ```
- **Escalation:** set `escalate=true` for high-signal / low-confidence / market-moving items → Phase 3.
- **Guardrails:** batch + bounded concurrency, a token/spend cap, structured-output validation, retry on bad JSON.
- **Output:** enriched JSONL (e.g. `outputs/triage_<date>.jsonl`).

## Phase 3 — Deep Scoring (quality, narrow)

- Only **escalated** articles. Selectable engine **claude | codex**, model + effort (orchestrator-style
  iTerm2 tab dispatch on subscription, $0 — reuse `~/Documents/orchestrator` spawn machinery).
- Careful per-ticker sentiment + rationale + signal tags. Pin the JSON contract via `--output-schema` (codex) /
  explicit format (claude). Deep score overrides the triage score where present.

## Phase 4 — Dashboard

- Static HTML from JSONL: sentiment by ticker / sector / tier over time; news vs social buckets kept separate;
  show triage-score vs deep-score. Build from the combined outputs.

---

## Open decisions / prerequisites

- **Before Phase 2:** obtain a Google AI API key (`export GOOGLE_API_KEY=...`); confirm the exact current
  Flash-Lite model id + pricing (plan was written with ~Jan-2026 model knowledge — verify the live name).
- Pin the Phase-2 extraction schema together before running at volume.
- Replace the PROVISIONAL `watchlist.json`; confirm the EDGAR contact email in `config.json` (`SSA.EDGAR_CONTACT`).
- Write the missing `memory/ai-buildout-investment-thesis.md` (the strategy north star).
- Decide whether legacy root files get moved to `legacy/` (flag before moving).
- Deferred free API keys (Marketaux / Finnhub / Alpha Vantage / NewsAPI / StockTwits) — wire in later.

---

## How to start the next phase (in a fresh chat)

> **Start Phase 2 (Triage & Extract) of the stock_sentaments rebuild. Read `PLAN.md` first — it's the source
> of truth. Begin with Phase 1b (biztoc full-text firehose: harvest all unread links vs `state/seen.json`,
> scrape full body, reuse `ssa/http.py`), then build the cheap triage/extract pass over ALL article records
> using the hosted Gemini Flash-Lite API (engine pluggable; key from `GOOGLE_API_KEY` env, gitignored). Pin the
> extraction schema with me before running at volume. Keep Phase 3 (claude/codex deep scoring) and Phase 4
> (dashboard) out of scope.**

*Have ready before that chat:* a `GOOGLE_API_KEY` in your env. *(Optional but ideal:* drop in the real
`watchlist.json` + write `memory/ai-buildout-investment-thesis.md` first.)*
