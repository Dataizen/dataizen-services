"""GeoJSON writer for the canonical TrafficObservation model.

City-aggregated observations have no road geometry, so we plot one
Point per observation at the city centroid. The actual differentiation
between observations is in the time and KPI properties, not space.
For mapping/visualisation, a UI typically picks one snapshot in time
and shows the city as a single coloured marker.
"""
from __future__ import annotations
from dataclasses import asdict
from typing import Iterable

from .model import TrafficObservation


def _flatten(prefix: str, value, target: dict) -> None:
    if value is None:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, target)
    else:
        target[prefix] = value


def obs_to_feature(obs: TrafficObservation, base_id: str) -> dict:
    props: dict = {"@id": f"{base_id}{obs.localId}", "@type": "TrafficObservation"}
    d = asdict(obs)
    city_dict = d.pop("city")
    for k, v in d.items():
        if v is not None:
            props[k] = v
    _flatten("city", city_dict, props)

    lat = obs.city.latitude
    lon = obs.city.longitude
    geom = {"type": "Point", "coordinates": [lon, lat]} if lon is not None and lat is not None else None

    feature = {"type": "Feature", "id": obs.localId, "properties": props}
    if geom:
        feature["geometry"] = geom
    return feature


def build_collection(observations: Iterable[TrafficObservation], base_id: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [obs_to_feature(o, base_id) for o in observations],
    }
