"""Adapter for the Porto Open Data Casas de Fado CSV (CitySDK schema).

Source quirks handled here:
    - The CSV uses Python dict-literal strings (single-quoted) inside
      multilingual fields, parsed via ast.literal_eval.
    - Address is a vCard 2.1 blob, ADR;WORK fields are extracted
      positionally per the spec (P.O. box; ext addr; street; locality;
      region; postal code; country).
    - The 'others' field is a list of {type, value} where type is a
      namespaced key like x-citysdk/capacity, x-citysdk/cost-rating, etc.

Maps to PointOfInterest via category_map.json lookup for schema.org IRIs.
"""
from __future__ import annotations
import ast
import csv
import json
import re
from pathlib import Path
from typing import Iterator

from ..model import (
    Category, ContactPoint, Location, LocalizedText, PointOfInterest,
    PostalAddress, normalize_lang,
)
from ..transforms import clean_text


def _load_category_map() -> dict:
    p = Path(__file__).resolve().parent.parent / "category_map.json"
    return json.loads(p.read_text(encoding="utf-8"))


_CATEGORY_MAP = _load_category_map()


def _safe_literal(raw: str | None):
    if not raw:
        return []
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return []


def _localized_list(raw: str | None, key_lang: str = "lang", key_val: str = "value", filter_term: str | None = None) -> list[LocalizedText]:
    out: list[LocalizedText] = []
    seen_langs: set[str] = set()
    for entry in _safe_literal(raw):
        if not isinstance(entry, dict):
            continue
        if filter_term and entry.get("term") != filter_term:
            continue
        lang = normalize_lang(entry.get(key_lang))
        val = clean_text(entry.get(key_val))
        if not val or lang in seen_langs:
            continue
        seen_langs.add(lang)
        out.append(LocalizedText(lang=lang, value=val))
    return out


def _resolve_category(raw: str | None) -> Category:
    items = _safe_literal(raw)
    pt_label = None
    for item in items:
        if isinstance(item, dict) and item.get("lang") == "pt-PT":
            pt_label = item.get("value")
            break
    label = pt_label or (items[0].get("value") if items and isinstance(items[0], dict) else "Unknown")
    label = clean_text(label) or "Unknown"
    mapped = _CATEGORY_MAP.get(label, {})
    return Category(
        sourceLabel=label,
        schemaOrgRefs=tuple(mapped.get("schemaOrgRefs", ["https://schema.org/Place"])),
        wikidataRef=mapped.get("wikidataRef"),
    )


_VCARD_KEYS = ("BEGIN", "VERSION", "REV", "N", "FN", "ORG", "ADR", "TEL", "URL", "EMAIL", "END")
_VCARD_FIELD = re.compile(r"(?:^|\s)(" + "|".join(_VCARD_KEYS) + r")(?:;[^:]+)?:(.*?)(?=\s(?:" + "|".join(_VCARD_KEYS) + r")(?:;[^:]+)?:|$)", re.DOTALL)


def _parse_vcard(vcard: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _VCARD_FIELD.finditer(vcard or ""):
        key = m.group(1).upper()
        val = m.group(2).strip()
        if key not in out:
            out[key] = val
    return out


def _parse_vcard_address(vcard: str) -> PostalAddress | None:
    fields = _parse_vcard(vcard)
    raw = fields.get("ADR")
    if not raw:
        return None
    parts = raw.split(";")
    while len(parts) < 7:
        parts.append("")
    _po, _ext, street, locality, _region, postal, country = parts[:7]
    return PostalAddress(
        streetName=clean_text(street),
        streetNumber=clean_text(_ext),
        locality=clean_text(locality),
        postalCode=clean_text(postal),
        country=clean_text(country),
    )


def _parse_vcard_contact(vcard: str) -> ContactPoint | None:
    fields = _parse_vcard(vcard)
    if not fields:
        return None
    email_raw = fields.get("EMAIL", "")
    email = email_raw.split("/")[0].split(",")[0].strip() if email_raw else None
    cp = ContactPoint(
        telephone=clean_text(fields.get("TEL")),
        website=clean_text(fields.get("URL")),
        email=clean_text(email),
    )
    return cp if any([cp.telephone, cp.website, cp.email]) else None


def _extract_others(raw: str | None) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for item in _safe_literal(raw):
        if isinstance(item, dict):
            t = item.get("type")
            v = item.get("value")
            if t and v is not None:
                out.setdefault(t, []).append(str(v))
    return out


def _safe_int(s) -> int | None:
    if s is None:
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def read(csv_path: str | Path) -> Iterator[PointOfInterest]:
    """Yield canonical PointOfInterest records from a Porto CitySDK CSV."""
    with Path(csv_path).open(encoding="utf-8") as f:
        reader = csv.DictReader(f, quotechar="'")
        for row in reader:
            others = _extract_others(row.get("others"))
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
            except (KeyError, ValueError, TypeError):
                continue

            names = _localized_list(row.get("label"), key_lang="lang", key_val="value", filter_term="primary")
            if not names:
                continue

            poi = PointOfInterest(
                localId=row.get("id") or "",
                names=names,
                descriptions=_localized_list(row.get("description")),
                category=_resolve_category(row.get("category")),
                location=Location(latitude=lat, longitude=lon),
                address=_parse_vcard_address(row.get("address") or ""),
                contact=_parse_vcard_contact(row.get("address") or ""),
                capacity=_safe_int(others.get("x-citysdk/capacity", [None])[0]),
                costRating=_safe_int(others.get("x-citysdk/cost-rating", [None])[0]),
            )
            yield poi
