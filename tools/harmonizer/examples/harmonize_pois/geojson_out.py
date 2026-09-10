"""GeoJSON writer for the canonical POI model.

FeatureCollection in WGS84. Properties are flattened with dotted keys
so non-LD tools (geojson.io, QGIS, Leaflet) can use the data directly.
"""
from __future__ import annotations
from dataclasses import asdict
from typing import Iterable

from .model import PointOfInterest


def _flatten(prefix: str, value, target: dict) -> None:
    if value is None or value == []:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, target)
    elif isinstance(value, (list, tuple)):
        if value and isinstance(value[0], dict) and {"lang", "value"} <= set(value[0]):
            for item in value:
                target[f"{prefix}_{item['lang']}"] = item["value"]
        else:
            target[prefix] = list(value)
    else:
        target[prefix] = value


def poi_to_feature(poi: PointOfInterest, base_id: str) -> dict:
    props: dict = {"@id": f"{base_id}{poi.localId}", "@type": "PointOfInterest"}
    props["localId"] = poi.localId
    _flatten("name", [{"lang": t.lang, "value": t.value} for t in poi.names], props)
    _flatten("description", [{"lang": t.lang, "value": t.value} for t in poi.descriptions], props)
    _flatten("category", {
        "sourceLabel": poi.category.sourceLabel,
        "schemaOrgRefs": list(poi.category.schemaOrgRefs),
        "wikidataRef": poi.category.wikidataRef,
    }, props)
    if poi.address is not None:
        _flatten("address", asdict(poi.address), props)
    if poi.contact is not None:
        _flatten("contact", asdict(poi.contact), props)
    if poi.capacity is not None:
        props["capacity"] = poi.capacity
    if poi.costRating is not None:
        props["costRating"] = poi.costRating

    return {
        "type": "Feature",
        "id": poi.localId,
        "geometry": {
            "type": "Point",
            "coordinates": [poi.location.longitude, poi.location.latitude],
        },
        "properties": props,
    }


def build_collection(pois: Iterable[PointOfInterest], base_id: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [poi_to_feature(p, base_id) for p in pois],
    }
