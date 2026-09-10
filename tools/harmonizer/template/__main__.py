"""CLI entry point.

Run with:
    python -m harmonize_<your_domain> \
        --adapter <source_name> \
        --input data.csv \
        --output out/entities.jsonld \
        --base-id "http://your-namespace/uc/name/"

TODO: rename the import paths below from `harmonizer_template` to the
name of your renamed package (`harmonize_books`, `harmonize_waste`, ...).

Live examples of richer CLIs (with external resolvers, additional
writers, cache flags):
  - harmonize/__main__.py        (UC1, GBIF resolver + cache + GeoJSON)
  - harmonize_pois/__main__.py   (UC2, GeoJSON option)
  - harmonize_traffic/__main__.py (UC4, DATEX II + GeoJSON options)
"""
from __future__ import annotations
import argparse
import importlib
import json
import sys
from pathlib import Path

# TODO: rename harmonizer_template → your package name
from harmonizer_template.geojson_out import build_collection
from harmonizer_template.jsonld import build_document


def _load_adapter(name: str):
    # TODO: rename harmonizer_template → your package name
    mod = importlib.import_module(f"harmonizer_template.adapters.{name}")
    if not hasattr(mod, "read"):
        raise SystemExit(f"adapter {name!r} has no read(path) function")
    return mod


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="harmonizer_template",  # TODO: rename
        description="Harmonize a dataset to a canonical Dolfin pivot and emit JSON-LD (+ optional GeoJSON).",
    )
    p.add_argument("--adapter", required=True, help="Adapter module name under <package>.adapters")
    p.add_argument("--input", required=True, type=Path, help="Source dataset path")
    p.add_argument("--output", required=True, type=Path, help="Destination JSON-LD file")
    p.add_argument("--base-id", default="http://example.org/entities/", help="IRI prefix for @id values")
    p.add_argument("--geojson", type=Path, help="Also emit a GeoJSON FeatureCollection")
    # TODO: add more output flags as you add writers (--datex2, --csv-out, ...)
    args = p.parse_args(argv)

    adapter = _load_adapter(args.adapter)
    print(f"Reading via adapter '{args.adapter}' from {args.input}...")
    entities = list(adapter.read(args.input))
    print(f"  {len(entities)} entities read")

    print(f"Writing JSON-LD to {args.output}...")
    doc = build_document(entities, base_id=args.base_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  done, {len(doc['@graph'])} entities in @graph")

    if args.geojson:
        print(f"Writing GeoJSON to {args.geojson}...")
        fc = build_collection(entities, base_id=args.base_id)
        args.geojson.parent.mkdir(parents=True, exist_ok=True)
        args.geojson.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  done, {len(fc['features'])} features")

    return 0


if __name__ == "__main__":
    sys.exit(main())
