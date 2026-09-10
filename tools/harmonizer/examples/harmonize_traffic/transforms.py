"""Reusable text transforms shared across adapters.

Adapters compose these helpers rather than reimplementing them. Helpers
are intentionally minimal: they only do generic text work (cleanup,
regex extraction, keyword routing). Anything dataset-specific belongs
in the adapter itself.
"""
from __future__ import annotations
import re
from typing import Optional


def clean_text(value: Optional[str]) -> Optional[str]:
    """Trim, collapse internal whitespace, return None for empty input."""
    if value is None:
        return None
    txt = re.sub(r"\s+", " ", str(value)).strip()
    return txt or None


def extract_count(value: Optional[str], pattern: str = r"\((\d+)") -> Optional[int]:
    """Pull an integer out of free text, e.g. '... (12 exemplares)' -> 12."""
    if value is None:
        return None
    m = re.search(pattern, value)
    return int(m.group(1)) if m else None


def match_keywords(value: Optional[str], keyword_map: dict[str, str]) -> Optional[str]:
    """Return the first enum value whose regex key matches the input.

    keyword_map: {regex_pattern: enum_value}, e.g.
        {r"conjunto\\s+arb[óo]re[op]": "TreeCluster",
         r"isolad": "IsolatedSpecimen"}
    Patterns are evaluated in insertion order, case-insensitive.
    """
    if not value:
        return None
    for pattern, enum_value in keyword_map.items():
        if re.search(pattern, value, re.IGNORECASE):
            return enum_value
    return None


class Registry:
    """Tiny dedupe registry for value-typed entities like Authority.

    Use when source data has many spelling variants of the same entity:
        reg = Registry({"ICNF": Authority(name="...", acronym="ICNF")})
        a = reg.resolve("ICNF (Instituto da Conservação ...)", needle="ICNF")
    The canonical instance is returned, ensuring downstream graphs share
    one node per real-world entity.
    """

    def __init__(self, known: dict | None = None):
        self._known = dict(known or {})

    def resolve(self, raw, needle: str | None = None, default=None):
        if raw is None:
            return default
        text = str(raw)
        if needle is not None and needle in text and needle in self._known:
            return self._known[needle]
        for key, val in self._known.items():
            if key in text:
                return val
        return default

    def get(self, key: str):
        return self._known.get(key)
