"""Skeleton adapter, copy and rename to add a new dataset.

Quick start:
  1. cp _template.py <your_source>.py
  2. Implement read(path) to yield canonical Entity instances.
  3. Run: python -m <your_package> --adapter <your_source> --input <path>

Contract:
  read(path) -> Iterator[Entity]

The adapter is the ONLY place that knows the source format. It:
  - parses CSV / JSON / GeoJSON / XML / API,
  - builds typed sub-entities (your model.py classes),
  - normalises enums via match_keywords + lookup tables,
  - dedupes shared entities via Registry,
  - yields canonical instances.

No writer logic, no external-API logic, no CLI logic in the adapter.

Live worked examples:
  - harmonize/adapters/porto.py        (UC1, GeoJSON, regex parsing of free-text)
  - harmonize_pois/adapters/porto_pois.py (UC2, dict-literals + vCard + category map)
  - harmonize_traffic/adapters/tomtom.py  (UC4, plain CSV)
"""
from __future__ import annotations
from pathlib import Path
from typing import Iterator

# TODO: rename harmonizer_template → your package name
from harmonizer_template.model import Entity, SubEntity
from harmonizer_template.transforms import (
    Registry, clean_text, extract_count, match_keywords,
)


# OPTIONAL: pre-populate a registry of known canonical sub-entities
# (e.g. Authority instances, Category instances) so multiple spelling
# variants in the source collapse to one canonical node.
_KNOWN = Registry({
    # "ICNF": SubEntity(name="Instituto da Conservação ...", refExt="..."),
})


# OPTIONAL: regex-driven enum routing for messy free-text fields.
_KIND_KEYWORDS = {
    # r"conjunto\s+arb[óo]re[op]": "TreeCluster",
    # r"isolad|exemplar\s+isolado": "IsolatedSpecimen",
}


def read(path: str | Path) -> Iterator[Entity]:
    """Yield canonical Entity instances parsed from `path`.

    TODO: replace the example below with your real parsing logic.
    """
    # Example for a CSV source:
    #
    # import csv
    # with Path(path).open(encoding="utf-8") as f:
    #     for row in csv.DictReader(f):
    #         yield Entity(
    #             localId=row["id"],
    #             # subEntity=SubEntity(
    #             #     name=clean_text(row["name"]) or "",
    #             #     refExt=row.get("uri") or None,
    #             # ),
    #             # extraAttribute=clean_text(row.get("foo")),
    #         )

    raise NotImplementedError(
        "Implement read() for your dataset. "
        "See harmonize/adapters/porto.py, harmonize_pois/adapters/porto_pois.py, "
        "or harmonize_traffic/adapters/tomtom.py for worked examples."
    )
