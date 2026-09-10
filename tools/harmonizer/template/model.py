"""Canonical model, dataclass mirrors of your .dolfin concepts.

TODO: replace this skeleton with your domain's entities.

For every Dolfin `concept Foo` you defined, add a corresponding
`@dataclass class Foo:` here. Optional Dolfin attributes become
typed `Optional[...]` fields with `default=None`. Multi-valued
attributes become `list[T]` with `default_factory=list`.

See live examples:
  - harmonize/model.py        (UC1, Tree + Species + Authority + ...)
  - harmonize_pois/model.py   (UC2, PointOfInterest + Category + LocalizedText + ...)
  - harmonize_traffic/model.py (UC4, TrafficObservation + City)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# TODO: replace with the closed enums from your .dolfin
EXAMPLE_ENUM_VALUES = {"ValueA", "ValueB", "Unknown"}


def normalize_enum(raw: Optional[str], allowed: set[str] = EXAMPLE_ENUM_VALUES, default: str = "Unknown") -> str:
    """Map a free-text value to a controlled enum, falling back to default."""
    if not raw:
        return default
    raw = raw.strip()
    return raw if raw in allowed else default


# TODO: a typed sub-entity that several top-level Entity records can share.
# Make it frozen so it's hashable for deduplication via transforms.Registry.
@dataclass(frozen=True)
class SubEntity:
    name: str
    refExt: Optional[str] = None


# TODO: your top-level entity. Rename, add fields.
@dataclass
class Entity:
    localId: str
    # subEntity: SubEntity                                 # required ref
    # location: Optional[Location] = None                  # optional ref
    # extraAttribute: Optional[str] = None
    # children: list[ChildEntity] = field(default_factory=list)
    pass
