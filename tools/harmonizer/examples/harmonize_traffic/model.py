"""Canonical TrafficObservation model, mirrors traffic.dolfin."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class City:
    name: str
    countryCode: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


@dataclass
class TrafficObservation:
    localId: str
    city: City
    observedAt: str
    trafficIndex: Optional[float] = None
    trafficIndexWeekAgo: Optional[float] = None
    observedAtWeekAgo: Optional[str] = None
    jamsDelaySeconds: Optional[float] = None
    jamsLengthKm: Optional[float] = None
    jamsCount: Optional[int] = None
    travelTimePer10kmMin: Optional[float] = None
    historicTravelTimePer10kmMin: Optional[float] = None
    delayMin: Optional[float] = None
    source: Optional[str] = None
