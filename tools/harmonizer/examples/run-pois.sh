#!/usr/bin/env bash
# Run the UC2 POIs harmonizer on both Porto CitySDK CSVs.
# Same adapter, same schema, two datasets, one canonical output each.
set -e
cd "$(dirname "$0")"

echo "== Casas de Fado =="
python3 -m harmonize_pois \
    --adapter porto_pois \
    --input inputs/uc2-pois-casas-de-fado.csv \
    --output outputs/pois-casas-de-fado.jsonld \
    --geojson outputs/pois-casas-de-fado.geojson \
    --base-id "http://mimathon.askem.eu/uc2/pois/"

echo
echo "== Postos de Abastecimento =="
python3 -m harmonize_pois \
    --adapter porto_pois \
    --input inputs/uc2-postos-abastecimento.csv \
    --output outputs/pois-postos.jsonld \
    --geojson outputs/pois-postos.geojson \
    --base-id "http://mimathon.askem.eu/uc2/pois/"
