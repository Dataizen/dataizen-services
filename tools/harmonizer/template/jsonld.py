"""JSON-LD writer for the canonical model.

TODO: customise CONTEXT to align with your target standards.
The pattern: map every canonical attribute to the right IRI from
schema.org, Smart Data Models, or any other vocabulary you target.

Live examples:
  - harmonize/jsonld.py        (UC1, Darwin Core dwc: + WGS84 geo:)
  - harmonize_pois/jsonld.py   (UC2, schema.org alignment)
  - harmonize_traffic/jsonld.py (UC4, SDM Transportation + schema.org)
"""
from __future__ import annotations
from dataclasses import asdict
from typing import Iterable

from .model import Entity


# TODO: replace with your own namespace
NS = "http://your-namespace/uc/name#"

# TODO: align term names to your target standards (schema.org, SDM, ...)
CONTEXT = {
    "@vocab": NS,
    "schema": "https://schema.org/",
    "geo": "https://www.w3.org/2003/01/geo/wgs84_pos#",

    # Entity types
    "Entity": NS + "Entity",
    "SubEntity": NS + "SubEntity",

    # Common scalar attribute mappings (uncomment + adapt)
    # "name": "schema:name",
    # "description": "schema:description",
    # "latitude": "geo:lat",
    # "longitude": "geo:long",

    # Resolvable IRI attributes: mark as @id so JSON-LD treats them as links
    "refExt": {"@id": NS + "refExt", "@type": "@id"},
}


def _strip_none(d):
    """Drop None values and empty lists from a (nested) dict."""
    if isinstance(d, dict):
        return {k: _strip_none(v) for k, v in d.items() if v is not None and v != []}
    if isinstance(d, list):
        return [_strip_none(x) for x in d]
    return d


def entity_to_node(entity: Entity, base_id: str) -> dict:
    """Render one canonical Entity as a JSON-LD node.

    TODO: customise to attach @type tags to nested sub-entities, e.g.:
        d["subEntity"] = {"@type": "SubEntity", **asdict(entity.subEntity)}
    """
    d = asdict(entity)
    d["@id"] = f"{base_id}{entity.localId}"
    d["@type"] = "Entity"
    return _strip_none(d)


def build_document(entities: Iterable[Entity], base_id: str) -> dict:
    """Build a JSON-LD document with @graph of all canonical entities."""
    return {
        "@context": CONTEXT,
        "@graph": [entity_to_node(e, base_id) for e in entities],
    }
