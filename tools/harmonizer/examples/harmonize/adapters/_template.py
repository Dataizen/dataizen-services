"""Skeleton adapter, copy and rename to add a new dataset.

Quick start:
    1. Copy this file to harmonize/adapters/<your_dataset>.py
    2. Replace the `read` function body with your own parsing
    3. Run:  python -m harmonize --adapter <your_dataset> --input ... --output ...

Contract:
    Expose a single function `read(path) -> Iterator[Tree]`.
    The CLI (harmonize/__main__.py) takes care of GBIF resolution and
    JSON-LD output, so the adapter only has to map source records to
    canonical Tree instances.

See harmonize/adapters/porto.py for a complete worked example covering
field renaming, enum normalization, kind/count splitting from free
text, and authority dedupe.
"""
from __future__ import annotations
from pathlib import Path
from typing import Iterator

from ..model import (
    AGE_RANGES,
    Authority, Classification, LegalAct, Location, Species, Tree,
    normalize_age,
)
from ..transforms import (
    Registry, clean_text, extract_count, match_keywords,
)


# Optional: pre-populate canonical entities you'll reuse, then dedupe via Registry.
_AUTHORITIES = Registry({
    # "ICNF": Authority(name="Instituto da Conservação ...", acronym="ICNF"),
})


# Optional: keyword-driven enum routing for messy free-text fields.
_KIND_KEYWORDS = {
    # r"conjunto\s+arb[óo]re[op]": "TreeCluster",
    # r"isolad|exemplar\s+isolado": "IsolatedSpecimen",
}


def read(path: str | Path) -> Iterator[Tree]:
    """Yield canonical Tree records from `path`.

    Replace the body below with your dataset's parsing logic. The
    important parts:

      - return Tree(localId=..., species=..., location=..., ...)
      - all string-valued attributes should already be cleaned
      - taxonRef is left for the CLI to fill via GBIF
      - if classification info is missing, set classification=None
    """
    # Example for a CSV: read it and iterate rows
    # import csv
    # with Path(path).open(encoding="utf-8") as f:
    #     for row in csv.DictReader(f):
    #         yield Tree(
    #             localId=row["id"],
    #             species=Species(
    #                 scientificName=clean_text(row["scientific_name"]) or "",
    #                 commonName=clean_text(row.get("common_name")),
    #             ),
    #             location=Location(
    #                 latitude=float(row["lat"]),
    #                 longitude=float(row["lon"]),
    #             ),
    #             ageRange=normalize_age(row.get("age_class")),
    #             classification=None,
    #         )
    raise NotImplementedError("Implement read() for your dataset, see porto.py")
