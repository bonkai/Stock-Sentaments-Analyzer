# Stock Sentiment Analyzer — Claude Guide

> ⚠️ **ACTIVE WORK IS A FRESH REBUILD — read `PLAN.md` (repo root) first; it is the source of truth.**
> Everything below describes the **LEGACY Ollama pipeline** (still at the repo root, not yet archived).
> The new stack lives in `ssa/` (Phase-1 scraper, `python -m ssa.scrape`, deps in `requirements.txt`,
> dedup in `state/seen.json`, output `outputs/articles_<date>.jsonl`). Do not move/delete legacy files
> without flagging. The new `.venv` (not `env/`) is the rebuild's environment.

---

## Pipeline (run in order)  *(LEGACY)*
```bash
python get_links.py        # 1. Scrape article URLs → processed_urls.txt
python extract_tickers.py  # 2. Match tickers → feeds scoring step
# 3. Scoring runs via Ollama (called internally, results → outputs/*.jsonl)
streamlit run app.py       # 4. Launch dashboard
```

## Key files
| File | Role |
|---|---|
| `config.json` | Model name, Ollama endpoint, output paths, rate-limit, user agents |
| `valid_tickers.txt` | Authoritative ticker list used by extract_tickers.py |
| `processed_urls.txt` | Dedup log — URLs already scraped |
| `outputs/*.jsonl` | Per-run sentiment results (one file per date) |
| `outputs/analyze_sentiments.py` | Standalone analysis script (not part of main pipeline) |
| `outputs/script.js` | Dashboard helper script for static HTML export |

## Dependencies
- Python 3.x with venv (`env/`)
- `pip install streamlit pandas matplotlib seaborn`
- [Ollama](https://ollama.ai) running locally; model configured in `config.json`
- No external API keys required

## Conventions
- Do not modify `processed_urls.txt` manually — it is the scrape dedup state.
- New JSONL output files are appended to `outputs/` named by date.
- `llm_raw_responses.log` and `script.log` are debug logs; safe to ignore or truncate.
