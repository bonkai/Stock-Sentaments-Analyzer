"""ssa.triage — Phase 2: cheap, wide LLM triage over ALL article records.

Hosted Gemini Flash-Lite-class engine (PAID — key from GOOGLE_API_KEY env or
gitignored .env). Run::

    python -m ssa.triage --dry-run     # free: counts + cost estimate
    python -m ssa.triage --limit 3     # smoke test
    python -m ssa.triage               # all untriaged articles (spend-capped)
"""

from .engine import GeminiEngine, TriageError, Usage, load_api_key
from .runner import run
from .schema import (
    EXTRACTION_KEYS,
    RESPONSE_SCHEMA,
    TRIAGE_SCHEMA_VERSION,
    build_prompt,
    validate_extraction,
)

__all__ = [
    "run", "GeminiEngine", "TriageError", "Usage", "load_api_key",
    "EXTRACTION_KEYS", "RESPONSE_SCHEMA", "TRIAGE_SCHEMA_VERSION",
    "build_prompt", "validate_extraction",
]
