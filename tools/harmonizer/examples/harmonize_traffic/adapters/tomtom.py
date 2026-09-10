"""Adapter for the Porto TomTom traffic indicators CSV.

Source columns:
    Country, City, UpdateTimeUTC,
    JamsDelay, TrafficIndexLive, JamsLengthInKms, JamsCount,
    TrafficIndexWeekAgo, UpdateTimeUTCWeekAgo,
    TravelTimeLivePer10KmsMins, TravelTimeHistoricPer10KmsMins,
    MinsDelay

Maps to TrafficObservation. UpdateTimeUTC is exported as MM:SS only,
without a date, so we keep it as an opaque source-side timestamp
string. Country and city names are normalised lightly.
"""
from __future__ import annotations
import csv
from pathlib import Path
from typing import Iterator

from ..model import City, TrafficObservation
from ..transforms import clean_text


# Approximate centroid of Porto (Wikidata Q45)
_KNOWN_CITY = {
    ("PRT", "porto"): City(
        name="Porto", countryCode="PRT", latitude=41.1496, longitude=-8.6109
    ),
}


def _safe_float(s):
    if s in (None, ""):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _safe_int(s):
    f = _safe_float(s)
    return int(round(f)) if f is not None else None


def _resolve_city(country: str, city: str) -> City:
    key = ((country or "").strip().upper(), (city or "").strip().lower())
    if key in _KNOWN_CITY:
        return _KNOWN_CITY[key]
    return City(name=(city or "").strip().title() or "Unknown", countryCode=(country or "").strip().upper() or "??")


def read(csv_path: str | Path) -> Iterator[TrafficObservation]:
    """Yield canonical TrafficObservation records from a TomTom CSV."""
    with Path(csv_path).open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            city = _resolve_city(row.get("Country"), row.get("City"))
            yield TrafficObservation(
                localId=f"{city.countryCode}-{city.name}-{idx:05d}",
                city=city,
                observedAt=(clean_text(row.get("UpdateTimeUTC")) or ""),
                observedAtWeekAgo=clean_text(row.get("UpdateTimeUTCWeekAgo")),
                trafficIndex=_safe_float(row.get("TrafficIndexLive")),
                trafficIndexWeekAgo=_safe_float(row.get("TrafficIndexWeekAgo")),
                jamsDelaySeconds=_safe_float(row.get("JamsDelay")),
                jamsLengthKm=_safe_float(row.get("JamsLengthInKms")),
                jamsCount=_safe_int(row.get("JamsCount")),
                travelTimePer10kmMin=_safe_float(row.get("TravelTimeLivePer10KmsMins")),
                historicTravelTimePer10kmMin=_safe_float(row.get("TravelTimeHistoricPer10KmsMins")),
                delayMin=_safe_float(row.get("MinsDelay")),
                source="TomTom",
            )
