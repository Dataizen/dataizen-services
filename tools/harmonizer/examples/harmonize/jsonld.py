"""JSON-LD serializer for the canonical Tree model.

Produces a single document with a @graph of all trees. Inline objects
for Species, Authority, LegalAct, Classification and Location, with
type tags so each fragment is independently identifiable.
"""
from __future__ import annotations
from dataclasses import asdict
from typing import Iterable

from .model import Tree


NS = "http://mimathon.askem.eu/uc1/trees#"

CONTEXT = {
    "@vocab": NS,
    "Tree": NS + "Tree",
    "Species": NS + "Species",
    "Authority": NS + "Authority",
    "LegalAct": NS + "LegalAct",
    "Classification": NS + "Classification",
    "Location": NS + "Location",
    "taxonRef": {"@id": NS + "taxonRef", "@type": "@id"},
    "refFlowerBed": {"@id": NS + "refFlowerBed", "@type": "@id"},
    "refGarden": {"@id": NS + "refGarden", "@type": "@id"},
    "geo": "https://www.w3.org/2003/01/geo/wgs84_pos#",
    "latitude": "geo:lat",
    "longitude": "geo:long",
    "dwc": "http://rs.tdwg.org/dwc/terms/",
    "scientificName": "dwc:scientificName",
    "commonName": "dwc:vernacularName",
}


def _strip_none(d):
    if isinstance(d, dict):
        return {k: _strip_none(v) for k, v in d.items() if v is not None}
    if isinstance(d, list):
        return [_strip_none(x) for x in d]
    return d


def tree_to_node(tree: Tree, base_id: str) -> dict:
    d = asdict(tree)
    d["@id"] = f"{base_id}{tree.localId}"
    d["@type"] = "Tree"
    d["species"] = {"@type": "Species", **asdict(tree.species)}
    d["location"] = {"@type": "Location", **asdict(tree.location)}
    if tree.classification is not None:
        c = asdict(tree.classification)
        c["@type"] = "Classification"
        c["authority"] = {"@type": "Authority", **asdict(tree.classification.authority)}
        c["legalAct"] = {"@type": "LegalAct", **asdict(tree.classification.legalAct)}
        d["classification"] = c
    return _strip_none(d)


def build_document(trees: Iterable[Tree], base_id: str) -> dict:
    return {
        "@context": CONTEXT,
        "@graph": [tree_to_node(t, base_id) for t in trees],
    }
