"""CLI entry point for the POI harmonizer.

Example:
    python -m harmonize_pois \
        --adapter porto_pois \
        --input ../uc2-pois-casas-de-fado.csv \
        --output ../out/pois.jsonld \
        --geojson ../out/pois.geojson \
        --base-id http://mimathon.askem.eu/uc2/pois/
"""
from __future__ import annotations
import argparse
import importlib
import json
import sys
from pathlib import Path

from .geojson_out import build_collection
from .jsonld import build_document


def _load_adapter(name: str):
    mod = importlib.import_module(f"harmonize_pois.adapters.{name}")
    if not hasattr(mod, "read"):
        raise SystemExit(f"adapter {name!r} has no read(path) function")
    return mod


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="harmonize_pois", description="Harmonize a POI dataset to the canonical PointOfInterest model and emit JSON-LD plus optional GeoJSON.")
    p.add_argument("--adapter", required=True, help="Adapter module name under harmonize_pois.adapters, e.g. porto_pois")
    p.add_argument("--input", required=True, type=Path, help="Source dataset path")
    p.add_argument("--output", required=True, type=Path, help="Destination JSON-LD file")
    p.add_argument("--base-id", default="http://example.org/pois/", help="IRI prefix for POI @id values")
    p.add_argument("--geojson", type=Path, help="Also emit a GeoJSON FeatureCollection")
    args = p.parse_args(argv)

    adapter = _load_adapter(args.adapter)
    print(f"Reading via adapter '{args.adapter}' from {args.input}...")
    pois = list(adapter.read(args.input))
    print(f"  {len(pois)} POIs read")

    print(f"Writing JSON-LD to {args.output}...")
    doc = build_document(pois, base_id=args.base_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  done, {len(doc['@graph'])} entities in @graph")

    if args.geojson:
        print(f"Writing GeoJSON to {args.geojson}...")
        fc = build_collection(pois, base_id=args.base_id)
        args.geojson.parent.mkdir(parents=True, exist_ok=True)
        args.geojson.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  done, {len(fc['features'])} features")

    return 0


if __name__ == "__main__":
    sys.exit(main())
