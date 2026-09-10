"""Canonical POI model, mirrors pois.dolfin v0.1.0."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


LANGUAGES = {"pt", "en", "es", "fr", "de", "it", "other"}


def normalize_lang(raw: str | None) -> str:
    if not raw:
        return "other"
    raw = raw.lower().split("-")[0]
    return raw if raw in LANGUAGES else "other"


@dataclass(frozen=True)
class LocalizedText:
    lang: str
    value: str


@dataclass(frozen=True)
class Category:
    sourceLabel: str
    schemaOrgRefs: tuple[str, ...]
    wikidataRef: Optional[str] = None


@dataclass(frozen=True)
class PostalAddress:
    streetName: Optional[str] = None
    streetNumber: Optional[str] = None
    locality: Optional[str] = None
    postalCode: Optional[str] = None
    country: Optional[str] = None


@dataclass(frozen=True)
class ContactPoint:
    telephone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None


@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float


@dataclass
class PointOfInterest:
    localId: str
    names: list[LocalizedText]
    category: Category
    location: Location
    descriptions: list[LocalizedText] = field(default_factory=list)
    address: Optional[PostalAddress] = None
    contact: Optional[ContactPoint] = None
    capacity: Optional[int] = None
    costRating: Optional[int] = None
