#!/usr/bin/env bash
# Run the UC4 traffic harmonizer on the TomTom CSV.
# Emits JSON-LD + DATEX II v3 XML + GeoJSON from one canonical record.
set -e
cd "$(dirname "$0")"
python3 -m harmonize_traffic \
    --adapter tomtom \
    --input inputs/uc4-traffic-tomtom.csv \
    --output outputs/traffic.jsonld \
    --datex2 outputs/traffic.datex2.xml \
    --geojson outputs/traffic.geojson \
    --base-id "http://mimathon.askem.eu/uc4/traffic/"
