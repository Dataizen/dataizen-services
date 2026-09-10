"""CLI entry point.

Example:
    python -m harmonize \
        --adapter porto \
        --input ../uc1-trees-porto.geojson \
        --output ../out/trees.jsonld \
        --base-id http://mimathon.askem.eu/uc1/trees/ \
        --gbif-cache ../out/.gbif_cache.json
"""
from __future__ import annotations
import argparse
import importlib
import json
import sys
from dataclasses import replace
from pathlib import Path

from .gbif import GbifResolver
from .geojson_out import build_collection
from .jsonld import build_document
from .model import Species, Tree


def _load_adapter(name: str):
    mod = importlib.import_module(f"harmonize.adapters.{name}")
    if not hasattr(mod, "read"):
        raise SystemExit(f"adapter {name!r} has no read(path) function")
    return mod


def _enrich_with_gbif(trees, resolver: GbifResolver):
    """Replace each tree.species with a copy carrying taxonRef when resolved."""
    seen: dict[str, Species] = {}
    for t in trees:
        sci = t.species.scientificName
        if sci in seen:
            yield replace(t, species=seen[sci])
            continue
        match = resolver.resolve(sci)
        if match:
            enriched = replace(t.species, taxonRef=match["url"])
            print(f"  GBIF {match['matchType']:>5}  {sci}  ->  {match['url']}")
        else:
            enriched = t.species
            print(f"  GBIF  MISS  {sci}")
        seen[sci] = enriched
        yield replace(t, species=enriched)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="harmonize", description="Harmonize an urban tree dataset to the canonical Tree model and emit JSON-LD.")
    p.add_argument("--adapter", required=True, help="Adapter module name under harmonize.adapters, e.g. porto")
    p.add_argument("--input", required=True, type=Path, help="Source dataset path")
    p.add_argument("--output", required=True, type=Path, help="Destination JSON-LD file")
    p.add_argument("--base-id", default="http://example.org/trees/", help="IRI prefix for tree @id values")
    p.add_argument("--gbif-cache", type=Path, default=Path(".gbif_cache.json"), help="On-disk GBIF lookup cache")
    p.add_argument("--no-gbif", action="store_true", help="Skip GBIF resolution (faster, offline)")
    p.add_argument("--geojson", type=Path, help="Also emit a GeoJSON FeatureCollection for GIS tools")
    args = p.parse_args(argv)

    adapter = _load_adapter(args.adapter)
    print(f"Reading via adapter '{args.adapter}' from {args.input}...")
    trees = list(adapter.read(args.input))
    print(f"  {len(trees)} trees read")

    if not args.no_gbif:
        print(f"Resolving species against GBIF (cache: {args.gbif_cache})...")
        resolver = GbifResolver(args.gbif_cache)
        trees = list(_enrich_with_gbif(trees, resolver))

    print(f"Writing JSON-LD to {args.output}...")
    doc = build_document(trees, base_id=args.base_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  done, {len(doc['@graph'])} entities in @graph")

    if args.geojson:
        print(f"Writing GeoJSON to {args.geojson}...")
        fc = build_collection(trees, base_id=args.base_id)
        args.geojson.parent.mkdir(parents=True, exist_ok=True)
        args.geojson.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  done, {len(fc['features'])} features")

    return 0


if __name__ == "__main__":
    sys.exit(main())
