# Pipeline Architecture

## Stage flow
1. `get_links.py` — HTTP scrape with rotating user agents; writes discovered URLs to `processed_urls.txt` (dedup guard).
2. `extract_tickers.py` — tokenizes article text and cross-references against `valid_tickers.txt`.
3. Scoring — article text + ticker list is sent to Ollama; response is a sentiment score per ticker. Results appended to `outputs/market_sentiment_results_<date>.jsonl`.
4. `app.py` — Streamlit dashboard that reads all JSONL files in `outputs/` and renders sentiment-over-time views. Also generates a static HTML export.

## Config.json fields (as documented in README)
- Model name and Ollama endpoint URL
- Output directory path
- Request throttle / rate-limit settings
- User agent rotation list

## Out-of-pipeline scripts
- `outputs/analyze_sentiments.py` — standalone analysis helper, not called by the main pipeline.
- `outputs/script.js` — used by the static HTML dashboard export.

## Data state
Latest JSONL runs: 2024-10-21 through 2024-10-27. The `processed_urls.txt` dedup log reflects articles scraped up to that period.
