"""Dedup: URL canonicalization, title normalization, and seen-state.

This is the highest-leverage, longest-lived decision in the scraper: every
record ``id`` is ``sha1(canonical_url | normalized_title)`` and every future
Phase-2 join keys off these two functions. **Changing either retroactively
rewrites all historical ids**, so the algorithms are versioned
(``CANON_VERSION`` / ``NORM_VERSION``) and the version is stamped into
``state/seen.json``.

Reconciling the pinned id with cross-source collapse
----------------------------------------------------
The PLAN pins ``id = sha1(canonical_url | normalized_title)`` (an AND of both
fields → the record's stable identity). But the same wire story shows up across
biztoc / GDELT / Yahoo under *different* URLs, so identity alone won't merge
them. We therefore separate the two concerns:

  * ``id`` uses the pinned AND-hash (identity).
  * Dedup detection (:class:`SeenState`) matches on canonical-URL **OR**
    title-hash. If *either* has been seen, the record is a duplicate.

So a story seen first via EDGAR and again via Yahoo (different URL, same
normalized title) collapses on the title hash, while an exact re-fetch collapses
on the URL — and the ``id`` formula is left exactly as pinned.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import unicodedata
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

log = logging.getLogger(__name__)

# Bump these (and document why) if the algorithms below change — historical ids
# computed under an older version are NOT comparable to new ones.
CANON_VERSION = 1
NORM_VERSION = 1

# Tracking / analytics query params stripped during canonicalization. Anything
# matching these exact keys or the utm_*/ga_* prefixes is dropped.
_TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "gclsrc", "msclkid", "mc_cid", "mc_eid",
    "igshid", "ref", "ref_src", "ref_url", "referrer", "source", "src",
    "cmpid", "ncid", "spm", "yclid", "_hsenc", "_hsmi", "vero_id", "oly_enc_id",
    "oly_anon_id", "wt_mc", "icid", "ito", "at_medium", "at_campaign",
    "guccounter", "guce_referrer", "guce_referrer_sig", "soc_src", "soc_trk",
    ".tsrc", "tsrc", "guccounter ",
}
_TRACKING_PREFIXES = ("utm_", "ga_", "pk_", "stm_", "at_custom", "ml_")

# Publisher suffixes stripped from titles before hashing, e.g. "Foo - Reuters".
# Matched case-insensitively against the tail after the final " - " / " | " / " — ".
_PUBLISHER_SUFFIXES = {
    "reuters", "bloomberg", "cnbc", "yahoo finance", "yahoo", "the motley fool",
    "motley fool", "seeking alpha", "marketwatch", "barron's", "barrons",
    "the wall street journal", "wsj", "financial times", "ft", "forbes",
    "business insider", "investing.com", "benzinga", "the information",
    "techcrunch", "the verge", "ars technica", "datacenter dynamics",
    "datacenterdynamics", "utility dive", "semiconductor engineering",
    "the new york times", "associated press", "ap", "cnn", "fortune",
    "axios", "tipranks", "zacks", "the globe and mail", "globe and mail",
}

_SUFFIX_SEPARATORS = (" - ", " | ", " — ", " – ", " :: ")
_WS_RE = re.compile(r"\s+")


def sha1_hex(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def canonicalize_url(url: str) -> str:
    """Return a canonical form of ``url`` for stable identity + dedup.

    Steps (CANON_VERSION=1):
      * lower-case scheme and host, strip a leading ``www.``
      * drop the fragment (``#...``)
      * remove tracking query params (utm_*/fbclid/ref/...), keep the rest
        sorted for stability
      * strip a trailing slash from non-root paths
      * collapse an empty/`http`-vs-`https` scheme to https-less comparison?  No
        — scheme is kept (http vs https are genuinely different endpoints) but
        normalized to lower case.
    """
    if not url:
        return ""
    url = url.strip()
    parts = urlsplit(url)

    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]

    # Rebuild netloc, preserving a non-default port but dropping userinfo.
    netloc = host
    if parts.port:
        default = (scheme == "http" and parts.port == 80) or (
            scheme == "https" and parts.port == 443
        )
        if not default:
            netloc = f"{host}:{parts.port}"

    # Filter tracking params; keep the remainder sorted.
    kept = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lk = key.lower()
        if lk in _TRACKING_PARAMS:
            continue
        if any(lk.startswith(p) for p in _TRACKING_PREFIXES):
            continue
        kept.append((key, value))
    kept.sort()
    query = urlencode(kept)

    path = parts.path or ""
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_title(title: str) -> str:
    """Return a normalized title for hashing/dedup (NORM_VERSION=1).

    Steps: NFKC unicode fold → ASCII-ify smart quotes/dashes → strip a trailing
    publisher suffix (" - Reuters", " | Bloomberg", ...) → lower-case → strip
    punctuation noise → collapse whitespace. Deliberately *not* so aggressive
    that genuinely distinct recurring headlines (e.g. "Market wrap") never
    collapse — we keep the substantive words.
    """
    if not title:
        return ""

    # Unicode normalize and replace common typographic variants.
    t = unicodedata.normalize("NFKC", title)
    replacements = {
        "‘": "'", "’": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", "…": "...", " ": " ",
        "​": "", "﻿": "",
    }
    for src, dst in replacements.items():
        t = t.replace(src, dst)

    # Strip a single trailing publisher suffix if the tail is a known source.
    for sep in _SUFFIX_SEPARATORS:
        idx = t.rfind(sep)
        if idx > 0:
            tail = t[idx + len(sep):].strip().lower().rstrip(".")
            if tail in _PUBLISHER_SUFFIXES:
                t = t[:idx]
                break

    t = t.lower()
    # Drop emoji / symbol codepoints; keep letters, numbers, and basic spacing.
    t = "".join(
        ch for ch in t
        if not unicodedata.category(ch).startswith(("So", "Sk", "Cs", "Co"))
    )
    # Replace any run of non-alphanumeric chars with a single space.
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def title_hash(title: str) -> str:
    """SHA1 of the normalized title — the cross-source dedup key."""
    return sha1_hex(normalize_title(title))


def make_id(url: str, title: str) -> str:
    """The pinned record id: ``sha1(canonical_url | normalized_title)``."""
    return sha1_hex(f"{canonicalize_url(url)}|{normalize_title(title)}")


class SeenState:
    """Load/save dedup state from ``state/seen.json``.

    Holds two sets — canonical URLs and title hashes. A record is a duplicate if
    *either* its canonical URL or its title hash has been seen before (see module
    docstring). Persisted atomically via temp-file + ``os.replace`` so a crash
    can't corrupt the JSON.
    """

    def __init__(self, path: str, urls: Optional[Iterable[str]] = None,
                 titles: Optional[Iterable[str]] = None) -> None:
        self.path = path
        self.urls: set[str] = set(urls or ())
        self.titles: set[str] = set(titles or ())

    @classmethod
    def load(cls, path: str) -> "SeenState":
        if not os.path.exists(path):
            log.info("No seen-state at %s — starting fresh.", path)
            return cls(path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read seen-state %s (%s) — starting fresh.", path, exc)
            return cls(path)

        file_canon = data.get("canon_version")
        file_norm = data.get("norm_version")
        if file_canon not in (None, CANON_VERSION) or file_norm not in (None, NORM_VERSION):
            log.warning(
                "seen.json was written under canon=%s/norm=%s but code is "
                "canon=%s/norm=%s — keys may not match; dedup may be imperfect "
                "until state is rebuilt.",
                file_canon, file_norm, CANON_VERSION, NORM_VERSION,
            )
        return cls(path, urls=data.get("urls", []), titles=data.get("titles", []))

    def is_seen(self, url: str, title: str) -> bool:
        """True if this canonical URL or title hash has been recorded."""
        return canonicalize_url(url) in self.urls or title_hash(title) in self.titles

    def add(self, url: str, title: str) -> None:
        self.urls.add(canonicalize_url(url))
        self.titles.add(title_hash(title))

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        payload = {
            "canon_version": CANON_VERSION,
            "norm_version": NORM_VERSION,
            "urls": sorted(self.urls),
            "titles": sorted(self.titles),
        }
        # Atomic write: temp file in the same dir, then os.replace.
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path) or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def __len__(self) -> int:
        return len(self.urls)
