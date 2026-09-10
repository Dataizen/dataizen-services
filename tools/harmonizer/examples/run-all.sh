#!/usr/bin/env bash
# Run all three harmonizers back to back.
set -e
cd "$(dirname "$0")"

echo "================================================"
echo "  UC1 · Trees"
echo "================================================"
./run-trees.sh "$@"
echo

echo "================================================"
echo "  UC2 · Points of Interest"
echo "================================================"
./run-pois.sh
echo

echo "================================================"
echo "  UC4 · Traffic"
echo "================================================"
./run-traffic.sh
echo

echo "================================================"
echo "  Done. Outputs in ./outputs/"
echo "================================================"
ls -la outputs/ | grep -v "^total\|^d" | grep -v "\.gbif_cache"
