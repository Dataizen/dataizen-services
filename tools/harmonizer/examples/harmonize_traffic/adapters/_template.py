"""Skeleton traffic adapter, copy and rename to add a new dataset.

Quick start:
    1. Copy to harmonize_traffic/adapters/<your_dataset>.py
    2. Replace the read() body with your own parsing
    3. Run:  python -m harmonize_traffic --adapter <your_dataset> ...

Contract:
    Expose a single function `read(path) -> Iterator[TrafficObservation]`.

See harmonize_traffic/adapters/tomtom.py for a worked example.
"""
from __future__ import annotations
from pathlib import Path
from typing import Iterator

from ..model import City, TrafficObservation
from ..transforms import clean_text


def read(path: str | Path) -> Iterator[TrafficObservation]:
    raise NotImplementedError("Implement read() for your dataset, see tomtom.py")
