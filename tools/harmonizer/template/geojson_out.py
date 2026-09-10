"""Optional GeoJSON writer.

Use when your domain has geographic features (point / line / polygon).
Flattens canonical entity properties to dotted-key strings so non-LD
tools (geojson.io, QGIS, Leaflet, Mapbox) can consume the data
directly.

Live examples:
  - harmonize/geojson_out.py        (UC1, tree points in WGS84)
  - harmonize_pois/geojson_out.py   (UC2, POI points with multilingual flatten)
  - harmonize_traffic/geojson_out.py (UC4, city centroid points)

TODO: adapt entity_to_feature() to pick the right geometry attribute
from your canonical entity (point, polygon, no geometry → drop the
geometry field).
"""
from __future__ import annotations
from dataclasses import asdict
from typing import Iterable

from .model import Entity


def _flatten(prefix: str, value, target: dict) -> None:
    """Flatten nested dicts to dotted-key string properties."""
    if value is None or value == []:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, target)
    elif isinstance(value, (list, tuple)):
        target[prefix] = list(value)
    else:
        target[prefix] = value


def entity_to_feature(entity: Entity, base_id: str) -> dict:
    """Render one canonical Entity as a GeoJSON Feature.

    TODO: set `geometry` from the right field of your entity.
    """
    props: dict = {"@id": f"{base_id}{entity.localId}", "@type": "Entity"}
    for k, v in asdict(entity).items():
        _flatten(k, v, props)

    feature: dict = {"type": "Feature", "id": entity.localId, "properties": props}

    # TODO: if your entity has a Location-like sub-entity, set geometry:
    # if entity.location is not None:
    #     feature["geometry"] = {
    #         "type": "Point",
    #         "coordinates": [entity.location.longitude, entity.location.latitude],
    #     }

    return feature


def build_collection(entities: Iterable[Entity], base_id: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [entity_to_feature(e, base_id) for e in entities],
    }
