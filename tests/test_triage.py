"""Phase-2 triage tests: schema validation, engine parsing/retry, runner.

No live API calls — the engine is exercised through a fake transport and the
runner through a fake engine. The ONLY paid path (GeminiEngine._post) is a
thin requests wrapper.
"""

import copy
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ssa.triage import schema  # noqa: E402
from ssa.triage.engine import GeminiEngine, TriageError, Usage  # noqa: E402
from ssa.triage.runner import run  # noqa: E402

VALID = {
    "tickers": ["NVDA"],
    "entities": ["Nvidia"],
    "event_type": "capex",
    "sentiment": [{"ticker": "NVDA", "score": 78, "direction": "bull"}],
    "signal_tags": ["hyperscaler-capex"],
    "key_figures": "$10B capex",
    "confidence": 0.9,
    "escalate": True,
}


# --- schema -----------------------------------------------------------------
def test_validate_accepts_valid_extraction():
    assert schema.validate_extraction(copy.deepcopy(VALID)) == []


def test_validate_rejects_missing_key():
    bad = {k: v for k, v in VALID.items() if k != "confidence"}
    assert any("confidence" in e for e in schema.validate_extraction(bad))


def test_validate_rejects_bad_enums_and_ranges():
    bad = copy.deepcopy(VALID)
    bad["event_type"] = "banana"
    bad["sentiment"][0]["score"] = 150
    bad["confidence"] = 1.5
    bad["escalate"] = "yes"
    errors = schema.validate_extraction(bad)
    assert len(errors) == 4


def test_normalize_uppercases_and_dedupes_tickers():
    obj = copy.deepcopy(VALID)
    obj["tickers"] = ["nvda", " NVDA ", "ceg"]
    schema.normalize_extraction(obj)
    assert obj["tickers"] == ["NVDA", "CEG"]


def test_build_prompt_includes_fields_and_truncates():
    art = {"source": "biztoc", "source_type": "news", "published": "2026-07-01",
           "title": "Big capex news", "summary_or_text": "x" * 50}
    p = schema.build_prompt(art, ["NVDA", "CEG"], max_chars=10)
    assert "Big capex news" in p and "NVDA, CEG" in p
    assert "xxxxxxxxxx …[truncated]" in p and "x" * 11 not in p


# --- engine (fake transport) ------------------------------------------------
def _gemini_response(obj, prompt_tokens=100, output_tokens=50, thought=0, finish="STOP"):
    return {
        "candidates": [{
            "content": {"parts": [{"text": json.dumps(obj)}]},
            "finishReason": finish,
        }],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": output_tokens,
            "thoughtsTokenCount": thought,
        },
    }


def _engine(responses):
    """GeminiEngine whose _post pops canned responses (no network)."""
    eng = GeminiEngine("test-key", "test-model")
    queue = list(responses)
    eng._post = lambda body: queue.pop(0)
    return eng


def test_engine_happy_path():
    eng = _engine([_gemini_response(VALID, 120, 40, 8)])
    extraction, usage, retries = eng.extract("prompt")
    assert extraction["tickers"] == ["NVDA"]
    assert (usage.prompt_tokens, usage.output_tokens, usage.thought_tokens) == (120, 40, 8)
    assert retries == 0


def test_engine_retries_once_on_invalid_then_succeeds():
    bad = copy.deepcopy(VALID)
    bad["event_type"] = "banana"
    eng = _engine([_gemini_response(bad, 100, 30), _gemini_response(VALID, 110, 35)])
    extraction, usage, retries = eng.extract("prompt")
    assert retries == 1
    assert usage.prompt_tokens == 210  # both calls are paid — both counted
    assert extraction["event_type"] == "capex"


def test_engine_fails_after_two_invalid():
    bad = copy.deepcopy(VALID)
    bad["confidence"] = 5
    eng = _engine([_gemini_response(bad), _gemini_response(bad)])
    with pytest.raises(TriageError, match="invalid extraction"):
        eng.extract("prompt")


def test_engine_raises_on_early_finish_and_block():
    with pytest.raises(TriageError, match="MAX_TOKENS"):
        _engine([_gemini_response(VALID, finish="MAX_TOKENS")]).extract("p")
    with pytest.raises(TriageError, match="blocked"):
        _engine([{"promptFeedback": {"blockReason": "SAFETY"}}]).extract("p")


def test_usage_cost_math():
    u = Usage(prompt_tokens=1_000_000, output_tokens=500_000, thought_tokens=500_000)
    assert u.cost_usd(0.25, 1.50) == pytest.approx(0.25 + 1.50)


# --- runner (fake engine) ---------------------------------------------------
class FakeEngine:
    name, model = "fake", "fake-1"

    def __init__(self, extraction=None, fail_titles=()):
        self.extraction = extraction or VALID
        self.fail_titles = fail_titles
        self.calls = 0

    def extract(self, prompt):
        self.calls += 1
        for t in self.fail_titles:
            if t in prompt:
                raise TriageError("boom")
        return copy.deepcopy(self.extraction), Usage(1000, 200, 0), 0


def _setup(tmp_path, n=3, cfg_extra=None):
    outdir = tmp_path / "outputs"
    outdir.mkdir()
    with open(outdir / "articles_2026-07-01.jsonl", "w", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({
                "id": f"id-{i}", "url": f"https://x.com/{i}", "title": f"Article {i}",
                "source": "biztoc", "source_type": "news", "published": None,
                "summary_or_text": f"Body text {i} about Nvidia.",
            }) + "\n")
    allow = tmp_path / "valid_tickers.txt"
    allow.write_text("NVDA\nCEG\n")
    ssa_cfg = {
        "OUTPUT_DIR": str(outdir),
        "WATCHLIST_FILE": str(tmp_path / "no_watchlist.json"),
        "TRIAGE_ALLOWLIST_FILE": str(allow),
        "TRIAGE_MAX_WORKERS": 2,
        "TRIAGE_SPEND_CAP_USD": 5.0,
    }
    ssa_cfg.update(cfg_extra or {})
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"SSA": ssa_cfg}))
    return str(cfg_path), outdir


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def test_runner_writes_enriched_records(tmp_path):
    cfg, outdir = _setup(tmp_path)
    summary = run(config_path=cfg, engine=FakeEngine())
    assert (summary["triaged"], summary["failed"]) == (3, 0)
    recs = _read_jsonl(summary["output"])
    assert len(recs) == 3
    r = recs[0]
    assert r["id"] == "id-0" and r["title"] == "Article 0"
    assert r["schema_version"] == schema.TRIAGE_SCHEMA_VERSION
    assert r["tickers"] == ["NVDA"] and r["escalate"] is True
    assert r["triage"]["model"] == "fake-1" and r["triage"]["cost_usd"] > 0


def test_runner_is_idempotent(tmp_path):
    cfg, outdir = _setup(tmp_path)
    run(config_path=cfg, engine=FakeEngine())
    second = FakeEngine()
    summary = run(config_path=cfg, engine=second)
    assert summary["todo"] == 0 and second.calls == 0
    assert len(_read_jsonl(summary["output"])) == 3  # nothing appended twice


def test_runner_respects_limit(tmp_path):
    cfg, _ = _setup(tmp_path)
    summary = run(config_path=cfg, engine=FakeEngine(), limit=1)
    assert summary["triaged"] == 1 and summary["already_triaged"] == 0


def test_runner_allowlist_rejects_unknown_tickers(tmp_path):
    cfg, _ = _setup(tmp_path, n=1)
    ext = copy.deepcopy(VALID)
    ext["tickers"] = ["NVDA", "FAKETICK"]
    ext["sentiment"].append({"ticker": "FAKETICK", "score": 90, "direction": "bull"})
    summary = run(config_path=cfg, engine=FakeEngine(extraction=ext))
    rec = _read_jsonl(summary["output"])[0]
    assert rec["tickers"] == ["NVDA"]
    assert rec["tickers_rejected"] == ["FAKETICK"]
    assert [s["ticker"] for s in rec["sentiment"]] == ["NVDA"]


def test_runner_spend_cap_halts_early(tmp_path):
    # each fake article costs (1000*0.25 + 200*1.5)/1e6 = $0.00055
    cfg, _ = _setup(tmp_path, cfg_extra={
        "TRIAGE_MAX_WORKERS": 1, "TRIAGE_SPEND_CAP_USD": 0.0005})
    summary = run(config_path=cfg, engine=FakeEngine())
    assert summary["capped"] is True
    assert summary["triaged"] == 1  # stopped after the first batch crossed the cap


def test_runner_isolates_failures_for_retry(tmp_path):
    cfg, _ = _setup(tmp_path)
    summary = run(config_path=cfg, engine=FakeEngine(fail_titles=("Article 1",)))
    assert (summary["triaged"], summary["failed"]) == (2, 1)
    assert len(_read_jsonl(summary["output"])) == 2
    # the failed id was NOT recorded, so the next run retries exactly it
    rerun = run(config_path=cfg, engine=FakeEngine())
    assert rerun["todo"] == 1 and rerun["triaged"] == 1


def test_runner_dry_run_needs_no_engine_and_estimates(tmp_path):
    cfg, outdir = _setup(tmp_path)
    summary = run(config_path=cfg, dry_run=True)
    assert summary["dry_run"] is True and summary["todo"] == 3
    assert summary["est_cost_usd"] > 0
    assert not os.path.exists(summary["output"])  # nothing written, nothing spent
