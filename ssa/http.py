"""Shared HTTP helper for ssa adapters.

Lifts the robustness patterns from the legacy root ``get_links.py`` — a
``requests.Session`` with a retry/backoff adapter and User-Agent handling — but
nothing else (no BeautifulSoup/spaCy/LLM machinery). Phase 1 is RSS/API-first,
so we mostly fetch feeds and JSON, not HTML.

Two UA policies coexist deliberately (see PLAN trade-offs):
  * Most adapters rotate a pool of browser User-Agents (``USER_AGENTS``).
  * EDGAR requires a STABLE, descriptive User-Agent carrying a real contact
    email (SEC fair-access). That adapter passes ``user_agent=`` explicitly.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter

try:  # urllib3 ships under requests.packages on some installs, standalone on others
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover - environment dependent
    from requests.packages.urllib3.util.retry import Retry  # type: ignore

log = logging.getLogger(__name__)

# Default browser UA pool, mirrors the legacy config's USER_AGENTS so we keep a
# single source of truth when config provides one.
_FALLBACK_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15"
)


class HttpClient:
    """A thin wrapper around a retrying ``requests.Session``.

    Adapters call :meth:`get` / :meth:`get_json`. The client enforces a polite
    inter-request delay and rotates browser User-Agents unless an adapter pins
    one (EDGAR does).
    """

    def __init__(
        self,
        user_agents: Optional[list[str]] = None,
        request_delay: float = 1.0,
        max_retries: int = 3,
        timeout: int = 30,
    ) -> None:
        self.user_agents = list(user_agents) if user_agents else [_FALLBACK_UA]
        self.request_delay = float(request_delay)
        self.timeout = timeout
        self._last_request_ts: float = 0.0

        self.session = requests.Session()
        retry = Retry(
            total=max_retries,
            backoff_factor=1,
            # Cap total backoff so a feed that hard-blocks our IP (e.g. Yahoo
            # returning 429 + a long Retry-After) fails fast instead of stalling
            # the whole run for minutes.
            backoff_max=8,
            status_forcelist=[403, 429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
            respect_retry_after_header=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    # -- internals ---------------------------------------------------------
    def _throttle(self) -> None:
        """Sleep so consecutive requests are at least ``request_delay`` apart."""
        if self.request_delay <= 0:
            return
        # time.monotonic() is allowed; we only need relative spacing.
        now = time.monotonic()
        wait = self.request_delay - (now - self._last_request_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_request_ts = time.monotonic()

    def _headers(self, user_agent: Optional[str]) -> dict:
        ua = user_agent or random.choice(self.user_agents)
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,application/json,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }

    # -- public API --------------------------------------------------------
    def get(
        self,
        url: str,
        user_agent: Optional[str] = None,
        params: Optional[dict] = None,
    ) -> requests.Response:
        """GET ``url`` and return the Response (raises on HTTP error)."""
        self._throttle()
        resp = self.session.get(
            url,
            headers=self._headers(user_agent),
            params=params,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp

    def get_text(self, url: str, user_agent: Optional[str] = None, params: Optional[dict] = None) -> str:
        return self.get(url, user_agent=user_agent, params=params).text

    def get_bytes(self, url: str, user_agent: Optional[str] = None, params: Optional[dict] = None) -> bytes:
        return self.get(url, user_agent=user_agent, params=params).content

    def get_json(self, url: str, user_agent: Optional[str] = None, params: Optional[dict] = None) -> dict:
        return self.get(url, user_agent=user_agent, params=params).json()

    def close(self) -> None:
        self.session.close()
