#!/usr/bin/env bash
# Run the UC1 trees harmonizer on the Porto GeoJSON.
# Emits JSON-LD (semantic, GBIF-anchored) + GeoJSON (GIS-ready).
# Add --no-gbif if you are offline.
set -e
cd "$(dirname "$0")"
python3 -m harmonize \
    --adapter porto \
    --input inputs/uc1-trees-porto.geojson \
    --output outputs/trees.jsonld \
    --geojson outputs/trees-canonical.geojson \
    --gbif-cache outputs/.gbif_cache.json \
    --base-id "http://mimathon.askem.eu/uc1/trees/" \
    "$@"
