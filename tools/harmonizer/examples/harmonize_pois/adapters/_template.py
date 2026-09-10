"""Skeleton POI adapter, copy and rename to add a new dataset.

Quick start:
    1. Copy to harmonize_pois/adapters/<your_dataset>.py
    2. Replace the read() body with your own parsing
    3. Run:  python -m harmonize_pois --adapter <your_dataset> --input ...

Contract:
    Expose a single function `read(path) -> Iterator[PointOfInterest]`.

Look at adapters/porto_pois.py for a worked example covering CitySDK
multilingual fields, vCard address parsing, and category lookup.
"""
from __future__ import annotations
from pathlib import Path
from typing import Iterator

from ..model import (
    Category, ContactPoint, Location, LocalizedText, PointOfInterest,
    PostalAddress, normalize_lang,
)
from ..transforms import clean_text


def read(path: str | Path) -> Iterator[PointOfInterest]:
    """Yield canonical PointOfInterest records from `path`.

    Replace the body below with your dataset's parsing logic.
    """
    # Example: a CSV with one POI per row
    # import csv
    # with Path(path).open(encoding="utf-8") as f:
    #     for row in csv.DictReader(f):
    #         yield PointOfInterest(
    #             localId=row["id"],
    #             names=[LocalizedText(lang=normalize_lang("en"), value=row["name"])],
    #             category=Category(
    #                 sourceLabel=row["category"],
    #                 schemaOrgRefs=("https://schema.org/Place",),
    #             ),
    #             location=Location(
    #                 latitude=float(row["lat"]),
    #                 longitude=float(row["lon"]),
    #             ),
    #         )
    raise NotImplementedError("Implement read() for your dataset, see porto_pois.py")
