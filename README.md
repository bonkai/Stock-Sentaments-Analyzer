# Stock Sentiment Analyzer

A scrape-to-model pipeline that pulls financial news from public sources, runs each
article through an LLM to extract per-ticker sentiment, and visualizes the results in
a dashboard.

## Pipeline

1. **Collect** (`get_links.py`) — gathers article URLs from public news sources, with
   rotating user agents and optional proxy support.
2. **Extract** (`extract_tickers.py`) — identifies stock tickers referenced in each
   article against a validated ticker list.
3. **Score** — sends article text to a local LLM (Ollama) which returns a sentiment
   score per ticker; results are appended as JSONL to `outputs/`.
4. **Visualize** (`app.py`) — a Streamlit dashboard consolidating all runs into
   sentiment-over-time views. A static HTML dashboard is also generated in `outputs/`.

## Stack

- Python, Streamlit, pandas, matplotlib/seaborn
- Ollama for local LLM inference (configured in `config.json`)

## Run

```bash
python -m venv env && source env/bin/activate
pip install streamlit pandas matplotlib seaborn
python get_links.py        # collect sources
python app.py              # or: streamlit run app.py  (dashboard)
```

> `config.json` controls the model, output paths, request throttling, and user agents.
> No API keys are stored — inference runs against a local Ollama endpoint.
