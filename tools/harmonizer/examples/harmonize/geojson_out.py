"""GeoJSON serializer for the canonical Tree model.

Emits a FeatureCollection in WGS84, suitable for any GIS tool
(geojson.io, QGIS, Mapbox, Leaflet). Nested entities are flattened
to a dotted-key namespace inside `properties` so the file is also
useful for non-LD-aware consumers.
"""
from __future__ import annotations
from dataclasses import asdict
from typing import Iterable

from .model import Tree


def _flatten(prefix: str, value, target: dict) -> None:
    if value is None:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, target)
    else:
        target[prefix] = value


def tree_to_feature(tree: Tree, base_id: str) -> dict:
    props: dict = {"@id": f"{base_id}{tree.localId}", "@type": "Tree"}
    _flatten("localId", tree.localId, props)
    _flatten("ageRange", tree.ageRange, props)
    _flatten("species", asdict(tree.species), props)
    if tree.classification is not None:
        _flatten("classification", asdict(tree.classification), props)
    if tree.refFlowerBed is not None:
        props["refFlowerBed"] = tree.refFlowerBed
    if tree.refGarden is not None:
        props["refGarden"] = tree.refGarden

    return {
        "type": "Feature",
        "id": tree.localId,
        "geometry": {
            "type": "Point",
            "coordinates": [tree.location.longitude, tree.location.latitude],
        },
        "properties": props,
    }


def build_collection(trees: Iterable[Tree], base_id: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [tree_to_feature(t, base_id) for t in trees],
    }
