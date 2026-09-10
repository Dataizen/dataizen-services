#!/usr/bin/env bash
# Synchronise les modules GÉNÉRIQUES du pivot-harmonizer vers l'extension CKAN
# ckanext-dataload-router (qui doit embarquer sa propre copie pour l'empaquetage).
# Source de vérité = ce dossier (dtz/tools/harmonizer/), lui-même vendorisé depuis
# le dépôt standalone gitlab.com/xpoxpo/pivot-harmonizer.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
EXT="$HERE/../../ckan/src/ckan-app/ckan/extensions/ckanext-dataload-router/ckanext/dataload_router"
for f in harmonize_generic.py references.py dolfin2model.py; do
  cp "$HERE/$f" "$EXT/$f"
  echo "synchronisé -> extension : $f"
done
echo "OK. Pensez à rebuild l'image CKAN si des modules ont changé."
