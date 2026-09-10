# Harmonizer (pivot + DOLFIN) dans Dataizen

Ce dossier vendorise le cœur réutilisable de `pivot-harmonizer` (méthode du pivot
+ langage DOLFIN), issu du **MIMaThon Porto 2026** (équipe LESL). Code Python pur,
sans dépendances, **licence MIT** (voir `LICENSE`), auteurs d'origine conservés.

## Provenance

Source amont : `gitlab.com/xpoxpo/pivot-harmonizer` (clone local
`/Users/xpo/DEV/OASC/mimathon/pivot-harmonizer/`). Vendorisé ici sans `.git` ni les
sorties générées. Le cœur MIMaThon (`dolfin2model.py`, `template/`, `examples/`,
`docs/`, `SKILL.md`) est **identique** à l'amont (diff vide).

### Modules génériques ajoutés par Dataizen (remontés à l'amont)
`harmonize_generic.py` (adaptateur tabulaire générique + writers NGSI-LD/CSV/GeoJSON)
et `references.py` (résolveurs de référentiels GBIF/Wikidata) sont des **créations
Dataizen** qui réutilisent la méthode ; ils sont contribués au dépôt standalone
(à sa racine, à côté de `dolfin2model.py`) + `tests/` (unittest, stdlib).

### Gouvernance du code (aller-retour)
- **Amont → Dataizen** : `git pull` dans le clone standalone, puis re-copier ici
  (sans `.git`, en conservant ce `DATAIZEN.md`).
- **Dataizen → amont** : améliorer ici, porter au standalone, `commit` + `push`
  GitLab, puis re-vendoriser.
- **tools/harmonizer → extension CKAN** : `./sync-to-ckan.sh` copie
  `harmonize_generic.py`, `references.py`, `dolfin2model.py` dans
  `ckanext-dataload-router` (qui embarque sa propre copie pour l'empaquetage).
  **Ce dossier est la source de vérité** ; ne pas éditer les copies de l'extension
  à la main. Rebuild l'image CKAN après un sync.
- **Tests** : `python3 -m unittest discover -s tests` (offline, sans réseau).

## Ce que c'est

Méthode « N in, M out, un pivot » : `sources → adaptateurs → modèle pivot (DOLFIN)
→ writers → SDM/NGSI-LD, GeoJSON, DATEX II`, avec « zéro dérive sémantique »
(les writers lisent tous le même modèle en mémoire).

- `dolfin2model.py` : compile un fichier `.dolfin` (langage de description du
  modèle) en dataclasses Python.
- `template/` : squelette pour un nouveau domaine (model, writers JSON-LD/GeoJSON,
  transforms, adaptateur `_template.py`).
- `examples/` : trois pipelines validées (arbres, POI, trafic) + jeux d'entrée.
- `docs/` : la méthode (`pattern.md`), la syntaxe DOLFIN (`writing-a-dolfin.md`),
  l'alignement aux standards (`standards-alignment.md`).

Lancer une pipeline d'exemple :

```bash
cd dtz/tools/harmonizer/examples && ./run-all.sh
```

## Intégration prévue dans Dataizen

Voir le backlog (section MDM, item « Intégrer le travail MIMaThon »). En résumé :

- **Phase 0 (fait)** : vendoring du cœur réutilisable.
- **Phase 1** : profils DOLFIN comme schémas `ckanext-scheming` (un profil par type
  de donnée), affichés sur la fiche, alignés au dictionnaire de données ; nourrit
  DCAT et le RAG.
- **Phase 2** : harmonisation par pivot greffée sur `dataload_router`, produisant
  au dépôt une ressource harmonisée SDM/NGSI-LD, avec un **adaptateur tabulaire
  générique piloté par un mapping** (champ DOLFIN ↔ colonne, édité dans le portail)
  pour éviter d'écrire un adaptateur Python par jeu.
- **Phase 3** : mapping proposé par la stack IA (le dossier `claude/` fournit un
  prompt d'onboarding LLM).

Nuance de grain : un modèle DOLFIN décrit **un domaine** (classe de données), pas
un jeu individuel ; les jeux référencent leur profil.

## Phase 2 (démarrée) : adaptateur tabulaire générique

`harmonize_generic.py` : harmonise n'importe quel CSV/tableau vers **NGSI-LD / JSON-LD**
(Smart Data Models) à partir d'un simple **mapping colonne → champ** aligné sur un modèle
DOLFIN, **sans coder d'adaptateur par domaine**. Stdlib pure, CLI ou importable
(`harmonize(rows, mapping)`). Valide le mapping contre le `.dolfin`.

```bash
python3 harmonize_generic.py --input data.csv --mapping mapping.json --output out.jsonld
```

C'est le moteur réutilisable. Reste à brancher (Phase 2, suite) : (a) génération de la
ressource harmonisée **au dépôt** dans `dataload_router` (mapping stocké en extra du jeu) ;
(b) **interface DOLFIN dans la forge** (admin.core) : gérer les `.dolfin`, éditer le mapping
colonne↔concept, déclencher l'harmonisation, prévisualiser.
