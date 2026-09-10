#!/usr/bin/env bash
# Référentiel territorial v0 : charge les communes de FRANCE ENTIÈRE
# (Code Officiel Géographique via geo.api.gouv.fr) dans mdm.communes
# de la base centrale (schéma mdm, base datastore).
#
# Rerunnable : la table est reconstruite à chaque exécution (référentiel
# de type "photo", versionné par la colonne valid_from).
# Usage : ./load_communes.sh
set -euo pipefail
cd "$(dirname "$0")"

CSV=/tmp/communes-france.csv

echo "== téléchargement du COG (geo.api.gouv.fr, France entière)"
curl -sf "https://geo.api.gouv.fr/communes?fields=nom,code,codeDepartement,codeRegion,codeEpci,population,siren&format=json" -o /tmp/communes-france.json

python3 - <<'PY'
import json, csv
data = json.load(open('/tmp/communes-france.json'))
with open('/tmp/communes-france.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['code_insee', 'nom', 'code_departement', 'code_region', 'code_epci', 'siren', 'population'])
    for c in sorted(data, key=lambda x: x['code']):
        w.writerow([c['code'], c['nom'], c.get('codeDepartement', ''), c.get('codeRegion', ''),
                    c.get('codeEpci', ''), c.get('siren', ''), c.get('population', '')])
print(f"communes France : {len(data)}")
PY

echo "== chargement dans mdm.communes (base centrale)"
ssh dtz-core "sudo docker exec -i shared.container.0 psql -U dataizen -d datastore -v ON_ERROR_STOP=1" <<'SQL'
DROP TABLE IF EXISTS mdm.communes;
CREATE TABLE mdm.communes (
  code_insee text PRIMARY KEY,
  nom text NOT NULL,
  code_departement text,
  code_region text,
  code_epci text,
  siren text,
  population integer,
  valid_from date NOT NULL DEFAULT current_date,
  source text NOT NULL DEFAULT 'geo.api.gouv.fr (COG)'
);
SQL

scp -q "$CSV" dtz-core:/tmp/
ssh dtz-core 'sudo docker cp /tmp/communes-france.csv shared.container.0:/tmp/ && \
  sudo docker exec shared.container.0 psql -U dataizen -d datastore -c \
  "\copy mdm.communes(code_insee,nom,code_departement,code_region,code_epci,siren,population) FROM /tmp/communes-france.csv CSV HEADER" && \
  sudo docker exec shared.container.0 psql -U dataizen -d datastore -tc \
  "SELECT count(*) || '\'' communes, population totale '\'' || sum(population) FROM mdm.communes"'

echo "== terminé. Publication CKAN : voir README.md (dataset referentiel-communes-france)"
