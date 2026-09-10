"""GBIF Backbone Taxonomy resolver, with on-disk cache.

Uses the public species/match endpoint, which fuzzy matches a scientific name
against the GBIF backbone and returns a stable usageKey. We turn that into
a canonical, resolvable URL: https://www.gbif.org/species/{usageKey}.

No external dependency, stdlib only.
"""
from __future__ import annotations
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional


GBIF_MATCH_URL = "https://api.gbif.org/v1/species/match"
GBIF_SPECIES_PAGE = "https://www.gbif.org/species/{key}"


class GbifResolver:
    """Resolve scientific names to GBIF species URLs, cached to disk."""

    def __init__(self, cache_path: Path, timeout: float = 10.0):
        self.cache_path = Path(cache_path)
        self.timeout = timeout
        self._cache: dict[str, dict] = {}
        if self.cache_path.exists():
            self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))

    def resolve(self, scientific_name: str) -> Optional[dict]:
        """Return {url, usageKey, canonicalName, matchType} or None on failure.

        Result is cached, including misses (stored as {"miss": true}) so a
        re-run does not pound the API for unmatched names.
        """
        key = scientific_name.strip()
        if not key:
            return None
        if key in self._cache:
            entry = self._cache[key]
            return None if entry.get("miss") else entry

        params = urllib.parse.urlencode({"name": key, "verbose": "false"})
        url = f"{GBIF_MATCH_URL}?{params}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as r:
                payload = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"  ! GBIF lookup failed for {key!r}: {e}")
            return None

        usage_key = payload.get("usageKey")
        if not usage_key or payload.get("matchType") == "NONE":
            self._cache[key] = {"miss": True}
            self._flush()
            return None

        entry = {
            "url": GBIF_SPECIES_PAGE.format(key=usage_key),
            "usageKey": usage_key,
            "canonicalName": payload.get("canonicalName") or payload.get("scientificName"),
            "matchType": payload.get("matchType"),
            "rank": payload.get("rank"),
        }
        self._cache[key] = entry
        self._flush()
        return entry

    def _flush(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
