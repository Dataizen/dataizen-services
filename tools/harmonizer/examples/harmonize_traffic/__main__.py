"""CLI entry point for the traffic harmonizer.

One canonical record, three output formats:

    python -m harmonize_traffic \
        --adapter tomtom \
        --input ../uc4-traffic-tomtom.csv \
        --output ../out/traffic.jsonld \
        --datex2 ../out/traffic.datex2.xml \
        --geojson ../out/traffic.geojson \
        --base-id http://mimathon.askem.eu/uc4/traffic/
"""
from __future__ import annotations
import argparse
import datetime
import importlib
import json
import sys
from pathlib import Path

from .datex2 import build_document as build_datex2
from .geojson_out import build_collection
from .jsonld import build_document as build_jsonld


def _load_adapter(name: str):
    mod = importlib.import_module(f"harmonize_traffic.adapters.{name}")
    if not hasattr(mod, "read"):
        raise SystemExit(f"adapter {name!r} has no read(path) function")
    return mod


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="harmonize_traffic", description="Harmonize a traffic dataset to the canonical TrafficObservation model and emit JSON-LD, DATEX II XML, and optional GeoJSON.")
    p.add_argument("--adapter", required=True)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path, help="Destination JSON-LD file")
    p.add_argument("--base-id", default="http://example.org/traffic/")
    p.add_argument("--datex2", type=Path, help="Also emit a DATEX II v3 XML file")
    p.add_argument("--geojson", type=Path, help="Also emit a GeoJSON FeatureCollection")
    args = p.parse_args(argv)

    adapter = _load_adapter(args.adapter)
    print(f"Reading via adapter '{args.adapter}' from {args.input}...")
    observations = list(adapter.read(args.input))
    print(f"  {len(observations)} observations read")

    print(f"Writing JSON-LD to {args.output}...")
    doc = build_jsonld(observations, base_id=args.base_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  done, {len(doc['@graph'])} entities in @graph")

    if args.datex2:
        print(f"Writing DATEX II XML to {args.datex2}...")
        pub_time = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        xml = build_datex2(observations, publication_time=pub_time)
        args.datex2.parent.mkdir(parents=True, exist_ok=True)
        args.datex2.write_text(xml, encoding="utf-8")
        print(f"  done, {len(observations)} siteMeasurements")

    if args.geojson:
        print(f"Writing GeoJSON to {args.geojson}...")
        fc = build_collection(observations, base_id=args.base_id)
        args.geojson.parent.mkdir(parents=True, exist_ok=True)
        args.geojson.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  done, {len(fc['features'])} features")

    return 0


if __name__ == "__main__":
    sys.exit(main())
