"""Triage engines. Phase 2 ships one: hosted Gemini (Flash-Lite-class, PAID).

The engine interface is deliberately tiny so it stays pluggable (PLAN):

    engine.name                      -> str
    engine.model                     -> str
    engine.extract(prompt) -> (extraction: dict, usage: Usage, retries: int)

``extract`` must return a schema-valid extraction or raise :class:`TriageError`
— the runner treats any exception as a per-article failure (isolation, like the
scrape adapters). Phase 3's claude/codex deep-scoring engines are separate.

The API key comes from the ``GOOGLE_API_KEY`` env var, falling back to a
gitignored ``.env`` at the repo root. NEVER commit or log the key.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

import requests
from requests.adapters import HTTPAdapter

try:  # same dual-home dance as ssa.http
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover - environment dependent
    from requests.packages.urllib3.util.retry import Retry  # type: ignore

from .schema import RESPONSE_SCHEMA, normalize_extraction, validate_extraction

log = logging.getLogger(__name__)

_API_ROOT = "https://generativelanguage.googleapis.com/v1beta"

_RETRY_SUFFIX = (
    "\n\nYour previous response failed validation: {errors}\n"
    "Return ONLY a JSON object that satisfies every rule above."
)


class TriageError(RuntimeError):
    """A per-article triage failure (bad response, blocked, invalid JSON)."""


def load_api_key(dotenv_path: str = ".env", env_var: str = "GOOGLE_API_KEY") -> Optional[str]:
    """GOOGLE_API_KEY from the environment, else from a gitignored .env file."""
    key = (os.environ.get(env_var) or "").strip()
    if key:
        return key
    if os.path.exists(dotenv_path):
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{env_var}="):
                    return line.split("=", 1)[1].strip().strip("'\"") or None
    return None


@dataclass
class Usage:
    """Token usage for one article (summed across a validation retry)."""

    prompt_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0  # billed at the output rate on thinking models

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.output_tokens + other.output_tokens,
            self.thought_tokens + other.thought_tokens,
        )

    def cost_usd(self, price_in_per_1m: float, price_out_per_1m: float) -> float:
        return (
            self.prompt_tokens * price_in_per_1m
            + (self.output_tokens + self.thought_tokens) * price_out_per_1m
        ) / 1_000_000


class GeminiEngine:
    """generateContent via REST (no SDK dep) with structured JSON output.

    Robustness: urllib3 retry on 429/5xx (respecting Retry-After), one
    validation retry with the errors echoed back, hard failure after that.
    """

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: int = 60,
        max_retries: int = 3,
        max_output_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature

        self.session = requests.Session()
        retry = Retry(
            total=max_retries,
            backoff_factor=2,
            backoff_max=30,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    # -- network -------------------------------------------------------------
    def _post(self, body: dict) -> dict:
        url = f"{_API_ROOT}/models/{self.model}:generateContent"
        resp = self.session.post(
            url,
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json=body,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _payload(self, prompt: str) -> dict:
        return {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
                "temperature": self.temperature,
                "maxOutputTokens": self.max_output_tokens,
            },
        }

    # -- public --------------------------------------------------------------
    def extract(self, prompt: str) -> tuple[dict, Usage, int]:
        """One article → validated extraction. Raises TriageError on failure."""
        usage = Usage()
        errors: list[str] = []
        for attempt in range(2):  # initial + one validation retry
            p = prompt if attempt == 0 else prompt + _RETRY_SUFFIX.format(errors="; ".join(errors))
            text, call_usage = _parse_response(self._post(self._payload(p)))
            usage = usage + call_usage
            try:
                obj = normalize_extraction(json.loads(text))
            except json.JSONDecodeError as exc:
                errors = [f"response is not valid JSON: {exc}"]
                continue
            errors = validate_extraction(obj)
            if not errors:
                return obj, usage, attempt
        raise TriageError(f"invalid extraction after retry: {'; '.join(errors)}")


def _parse_response(data: dict) -> tuple[str, Usage]:
    """Pull the JSON text + usage out of a generateContent response."""
    feedback = data.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        raise TriageError(f"prompt blocked: {feedback['blockReason']}")

    candidates = data.get("candidates") or []
    if not candidates:
        raise TriageError("no candidates in response")
    cand = candidates[0]

    finish = cand.get("finishReason")
    if finish not in (None, "STOP"):
        raise TriageError(f"generation stopped early: {finish}")

    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    if not text:
        raise TriageError("empty response text")

    meta = data.get("usageMetadata") or {}
    usage = Usage(
        prompt_tokens=int(meta.get("promptTokenCount", 0)),
        output_tokens=int(meta.get("candidatesTokenCount", 0)),
        thought_tokens=int(meta.get("thoughtsTokenCount", 0)),
    )
    return text, usage
