"""Adapter for the Porto Open Data classified-trees GeoJSON.

Worked example of an adapter using harmonize.transforms helpers.

Source schema (per feature.properties):
    objectid              -> Tree.localId
    especie               -> Species.scientificName
    esp_nomecomum         -> Species.commonName
    arv_intervalo_idade   -> Tree.ageRange
    classif_tutela        -> Classification.authority (registry)
    classif_tipo          -> Classification.kind + .specimenCount (parse)
    classif_dec_lei_ref   -> Classification.legalAct.reference (clean)
    classif_data          -> Classification.classifiedOn

Geometry: Point in WGS84, [lon, lat] order.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Iterator

from ..model import (
    Authority, Classification, LegalAct, Location, Species, Tree, normalize_age,
)
from ..transforms import Registry, clean_text, extract_count, match_keywords


_AUTHORITIES = Registry({
    "ICNF": Authority(
        name="Instituto da Conservação da Natureza e das Florestas",
        acronym="ICNF",
    ),
})

_KIND_KEYWORDS = {
    r"conjunto\s+arb[óo]re[op]": "TreeCluster",
    r"isolad|exemplar\s+isolado|árvore\s+isolada": "IsolatedSpecimen",
}


def _parse_authority(raw: str | None) -> Authority | None:
    found = _AUTHORITIES.resolve(raw, needle="ICNF")
    if found:
        return found
    txt = clean_text(raw)
    return Authority(name=txt, acronym=txt[:8]) if txt else None


def _parse_kind_and_count(raw: str | None) -> tuple[str | None, int | None]:
    return match_keywords(raw, _KIND_KEYWORDS), extract_count(raw, r"\((\d+)\s*exemplares?")


def _normalize_legal_ref(raw: str | None) -> str | None:
    """Collapse Porto variants like 'D. R.' / 'D.R.' to 'D.R.'."""
    txt = clean_text(raw)
    if txt is None:
        return None
    txt = re.sub(r"D\.\s*R\.", "D.R.", txt)
    txt = re.sub(r"D\.\s*G\.", "D.G.", txt)
    return txt


def _build_classification(props: dict) -> Classification | None:
    authority = _parse_authority(props.get("classif_tutela"))
    kind, count = _parse_kind_and_count(props.get("classif_tipo"))
    legal_ref = _normalize_legal_ref(props.get("classif_dec_lei_ref"))
    classified_on = clean_text(props.get("classif_data"))

    if not (authority or kind or legal_ref):
        return None

    return Classification(
        kind=kind or "IsolatedSpecimen",
        authority=authority or Authority(name="Unknown", acronym="UNK"),
        legalAct=LegalAct(reference=legal_ref or "(unspecified)"),
        specimenCount=count,
        classifiedOn=classified_on,
    )


def read(geojson_path: str | Path) -> Iterator[Tree]:
    """Yield canonical Tree records from a Porto GeoJSON file."""
    data = json.loads(Path(geojson_path).read_text(encoding="utf-8"))
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        if len(coords) < 2 or coords[0] is None:
            continue

        scientific = clean_text(props.get("especie"))
        if not scientific:
            continue

        yield Tree(
            localId=str(props.get("objectid") or feat.get("id") or ""),
            species=Species(
                scientificName=scientific,
                commonName=clean_text(props.get("esp_nomecomum")),
            ),
            location=Location(latitude=float(coords[1]), longitude=float(coords[0])),
            ageRange=normalize_age(props.get("arv_intervalo_idade")),
            classification=_build_classification(props),
        )
