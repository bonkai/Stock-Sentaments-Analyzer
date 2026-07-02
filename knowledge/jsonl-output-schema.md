# JSONL Output Schema

## File naming
`outputs/market_sentiment_results_<YYYY-MM-DD>.jsonl` — one file per pipeline run date.

## Known fields (inferred from file names and pipeline design)
Each line is a JSON object. The exact field names should be verified by reading one record:
```bash
head -1 outputs/market_sentiment_results_2024-10-21.jsonl | python3 -m json.tool
```

Expected fields based on pipeline design:
- Ticker symbol
- Sentiment score (numeric; range and sign convention unknown until verified)
- Source article URL or identifier
- Timestamp or date
- Possibly: raw LLM response excerpt

**Action needed:** Read one JSONL record and fill in the actual field names and score range here. This is required before the orchestrator can write correct analysis or visualization code.
