"""Canonical urban tree model, mirrors trees.dolfin v0.2.0."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional


AGE_RANGES = {
    "21-30": "Y21_30",
    "31-40": "Y31_40",
    "41-50": "Y41_50",
    "51-60": "Y51_60",
    "61-70": "Y61_70",
    "71-80": "Y71_80",
    "81-100": "Y81_100",
    "sup 100": "Over100",
    "": "Unknown",
    None: "Unknown",
}


@dataclass(frozen=True)
class Authority:
    name: str
    acronym: str


@dataclass(frozen=True)
class Species:
    scientificName: str
    commonName: Optional[str] = None
    taxonRef: Optional[str] = None


@dataclass(frozen=True)
class LegalAct:
    reference: str
    issuedOn: Optional[str] = None


@dataclass
class Classification:
    kind: str
    authority: Authority
    legalAct: LegalAct
    specimenCount: Optional[int] = None
    classifiedOn: Optional[str] = None


@dataclass
class Location:
    latitude: float
    longitude: float


@dataclass
class Tree:
    localId: str
    species: Species
    location: Location
    ageRange: Optional[str] = None
    classification: Optional[Classification] = None
    refFlowerBed: Optional[str] = None
    refGarden: Optional[str] = None


def normalize_age(raw: Optional[str]) -> str:
    if raw is None:
        return "Unknown"
    return AGE_RANGES.get(raw.strip(), "Unknown")
