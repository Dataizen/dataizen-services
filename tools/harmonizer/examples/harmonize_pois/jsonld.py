"""JSON-LD writer for the canonical POI model.

Aligns with schema.org for shared terms (name, description, address,
category) so the output is directly consumable by schema.org-aware
tools, while keeping a local namespace for the wrapping shape.
"""
from __future__ import annotations
from dataclasses import asdict
from typing import Iterable

from .model import PointOfInterest


NS = "http://mimathon.askem.eu/uc2/pois#"

CONTEXT = {
    "@vocab": NS,
    "schema": "https://schema.org/",
    "wd": "https://www.wikidata.org/entity/",
    "PointOfInterest": NS + "PointOfInterest",
    "Category": NS + "Category",
    "Location": NS + "Location",
    "PostalAddress": "schema:PostalAddress",
    "ContactPoint": "schema:ContactPoint",
    "LocalizedText": NS + "LocalizedText",
    "names": "schema:name",
    "descriptions": "schema:description",
    "category": "schema:category",
    "location": "schema:location",
    "address": "schema:address",
    "contact": "schema:contactPoint",
    "telephone": "schema:telephone",
    "email": "schema:email",
    "website": "schema:url",
    "streetName": "schema:streetAddress",
    "streetNumber": "schema:streetAddress",
    "locality": "schema:addressLocality",
    "postalCode": "schema:postalCode",
    "country": "schema:addressCountry",
    "schemaOrgRefs": {"@id": NS + "schemaOrgRefs", "@type": "@id"},
    "wikidataRef": {"@id": NS + "wikidataRef", "@type": "@id"},
    "geo": "https://www.w3.org/2003/01/geo/wgs84_pos#",
    "latitude": "geo:lat",
    "longitude": "geo:long",
    "lang": "@language",
    "value": "@value",
    "capacity": "schema:maximumAttendeeCapacity",
}


def _strip_none(d):
    if isinstance(d, dict):
        return {k: _strip_none(v) for k, v in d.items() if v is not None and v != []}
    if isinstance(d, list):
        return [_strip_none(x) for x in d]
    return d


def _localized(items) -> list[dict]:
    return [{"@language": t.lang, "@value": t.value} for t in items]


def poi_to_node(poi: PointOfInterest, base_id: str) -> dict:
    node = {
        "@id": f"{base_id}{poi.localId}",
        "@type": "PointOfInterest",
        "localId": poi.localId,
        "names": _localized(poi.names),
        "descriptions": _localized(poi.descriptions),
        "category": {
            "@type": "Category",
            "sourceLabel": poi.category.sourceLabel,
            "schemaOrgRefs": list(poi.category.schemaOrgRefs),
            "wikidataRef": poi.category.wikidataRef,
        },
        "location": {
            "@type": "Location",
            "latitude": poi.location.latitude,
            "longitude": poi.location.longitude,
        },
        "capacity": poi.capacity,
        "costRating": poi.costRating,
    }
    if poi.address is not None:
        node["address"] = {"@type": "PostalAddress", **asdict(poi.address)}
    if poi.contact is not None:
        node["contact"] = {"@type": "ContactPoint", **asdict(poi.contact)}
    return _strip_none(node)


def build_document(pois: Iterable[PointOfInterest], base_id: str) -> dict:
    return {
        "@context": CONTEXT,
        "@graph": [poi_to_node(p, base_id) for p in pois],
    }
