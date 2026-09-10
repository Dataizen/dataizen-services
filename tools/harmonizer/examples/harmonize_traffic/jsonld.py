"""JSON-LD writer for the canonical TrafficObservation model.

Aligns where possible to Smart Data Models conventions. SDM's
TrafficFlowObserved targets per-lane/per-segment observations, while
our records are city-aggregated KPIs. We adopt SDM attribute names
where they apply (`dateObserved`, `congested` derived from `trafficIndex`,
`refLocation` for the city) and extend with a custom KPI namespace
for the ones SDM does not cover (`jamsLengthKm`, `trafficIndex`,
`travelTimePer10kmMin`, ...).
"""
from __future__ import annotations
from dataclasses import asdict
from typing import Iterable

from .model import TrafficObservation


NS = "http://mimathon.askem.eu/uc4/traffic#"

CONTEXT = {
    "@vocab": NS,
    "sdm": "https://smartdatamodels.org/dataModel.Transportation/",
    "schema": "https://schema.org/",
    "TrafficObservation": NS + "TrafficObservation",
    "City": NS + "City",
    "city": "schema:location",
    "observedAt": "sdm:dateObserved",
    "observedAtWeekAgo": NS + "observedAtWeekAgo",
    "trafficIndex": NS + "trafficIndex",
    "trafficIndexWeekAgo": NS + "trafficIndexWeekAgo",
    "jamsDelaySeconds": NS + "jamsDelaySeconds",
    "jamsLengthKm": NS + "jamsLengthKm",
    "jamsCount": NS + "jamsCount",
    "travelTimePer10kmMin": NS + "travelTimePer10kmMin",
    "historicTravelTimePer10kmMin": NS + "historicTravelTimePer10kmMin",
    "delayMin": NS + "delayMin",
    "source": "schema:provider",
    "geo": "https://www.w3.org/2003/01/geo/wgs84_pos#",
    "latitude": "geo:lat",
    "longitude": "geo:long",
    "name": "schema:name",
    "countryCode": "schema:addressCountry",
}


def _strip_none(d):
    if isinstance(d, dict):
        return {k: _strip_none(v) for k, v in d.items() if v is not None}
    if isinstance(d, list):
        return [_strip_none(x) for x in d]
    return d


def obs_to_node(obs: TrafficObservation, base_id: str) -> dict:
    d = asdict(obs)
    d["@id"] = f"{base_id}{obs.localId}"
    d["@type"] = "TrafficObservation"
    d["city"] = {"@type": "City", **asdict(obs.city)}
    return _strip_none(d)


def build_document(observations: Iterable[TrafficObservation], base_id: str) -> dict:
    return {
        "@context": CONTEXT,
        "@graph": [obs_to_node(o, base_id) for o in observations],
    }
