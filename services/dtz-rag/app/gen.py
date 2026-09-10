# -*- coding: utf-8 -*-
"""Outils IA de génération d'éléments de page Directus à partir des données.

`generate_chart` : à partir d'un jeu CKAN (colonnes du datastore) et d'une intention
en langage naturel, propose une configuration de graphique via le LLM souverain et
crée l'item `graphiques` (statut brouillon) dans le Directus de l'instance."""
import json
import logging
import re
import unicodedata

import httpx

from . import config, llm

log = logging.getLogger("dtz-rag.gen")


def _slugify(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "page"

CHART_TYPES = ["bar", "line", "area", "pie", "gauge", "scatter"]
AGG = ["none", "sum", "avg", "count"]


def _isnum(v):
    """Vrai si la valeur (souvent une chaîne côté datastore) est numérique."""
    if isinstance(v, (int, float)):
        return True
    try:
        float(str(v).strip().replace(",", ".").replace(" ", ""))
        return True
    except (ValueError, AttributeError):
        return False


async def _ckan(action, params):
    headers = {"Authorization": config.CKAN_TOKEN} if config.CKAN_TOKEN else {}
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.get(f"{config.CKAN_URL}/api/3/action/{action}", params=params, headers=headers)
        r.raise_for_status()
        return r.json()["result"]


async def _resource_and_columns(dataset):
    pkg = await _ckan("package_show", {"id": dataset})
    res = next((r for r in pkg.get("resources", [])
                if r.get("datastore_active") and not r.get("harmonized_from")), None)
    if not res:
        return pkg, None, []
    info = await _ckan("datastore_search", {"resource_id": res["id"], "limit": 3})
    cols = [f["id"] for f in info.get("fields", []) if f.get("id") != "_id"]
    sample = [{k: v for k, v in rec.items() if k != "_id"} for rec in info.get("records", [])]
    return pkg, res, (cols, sample)


# Référence de syntaxe .dolfin injectée dans le prompt de génération (condensé de
# tools/harmonizer/docs/writing-a-dolfin.md + un exemple). Sert de spécification à l'IA.
DOLFIN_SYNTAX = """SYNTAXE d'un modèle canonique .dolfin :
package <http://espace-de-noms/uc/nom>:
  dolfin_version "1"
  version "0.1.0"
  author "équipe"
  description "rationale en une phrase"

concept UnEnum:
  one of:
    ValeurA
    ValeurB
    Unknown

concept SousEntite:
  has name: one string
  has refExt: optional string

concept EntitePrincipale:
  has localId: one string
  has sousEntite: one SousEntite
  has statut: optional UnEnum
  has tags: at least 1 string

CARDINALITÉS : `one T` (obligatoire), `optional T` (facultatif), `at least 1 T` (liste non
vide), `at least N/at most N/exactly N/between N M T` (liste bornée), sans mot-clé = liste
quelconque. TYPES primitifs : string, int, float, boolean ; tout autre nom = référence à un
autre concept.
RÈGLES : sortir les champs catégoriels à valeurs fermées en `concept ... one of` ; regrouper les
attributs liés en sous-concepts ; donner un `localId` à l'entité principale ; ajouter un
`refExt: optional string` aux concepts à identité publique stable (IRI GBIF, schema.org,
Wikidata) ; si le jeu est géolocalisé, prévoir un concept Location (latitude: one float,
longitude: one float) ; aligner les noms d'attributs sur les standards existants (Smart Data
Models, INSPIRE, schema.org, DATEX II) quand ils conviennent.
EXEMPLE :
package <http://exemple/uc/pois>:
  dolfin_version "1"
  version "0.1.0"
  author "équipe"
  description "Points d'intérêt multilingues, alignés schema.org."

concept Language:
  one of:
    fr
    en
    other

concept LocalizedText:
  has lang: one Language
  has value: one string

concept Location:
  has latitude: one float
  has longitude: one float

concept PointOfInterest:
  has localId: one string
  has names: at least 1 LocalizedText
  has category: one string
  has location: one Location
  has capacity: optional int
"""


def _dolfin_main_concept(src):
    """Nom du concept principal d'un .dolfin (celui portant `has localId`), sinon le
    dernier concept déclaré. Sert à pré-remplir le `type` du modèle."""
    cur, main, last = None, None, None
    for line in (src or "").splitlines():
        m = re.match(r"\s*concept\s+([A-Za-z_]\w*)\s*:", line)
        if m:
            cur = m.group(1)
            last = cur
        elif re.match(r"\s*has\s+localId\s*:", line) and cur and not main:
            main = cur
    return main or last or "Entity"


async def generate_dolfin_model(dataset):
    """Génère un BROUILLON de modèle canonique .dolfin par IA à partir d'un jeu tabulaire
    (colonnes + échantillon + titre/description) et de la syntaxe DOLFIN. Base éditable :
    l'appelant la relit, l'ajuste, puis l'enregistre via l'action CKAN `dolfin_model_save`
    (qui compile et versionne). Lève GpuWarming au cold-start, ValueError si pas de datastore."""
    pkg, res, colinfo = await _resource_and_columns(dataset)
    if not res:
        raise ValueError("aucune ressource tabulaire (datastore) pour ce jeu")
    cols, sample = colinfo
    sysp = ("Tu es un expert de la modélisation de données ouvertes territoriales et du langage "
            "DOLFIN (modèle canonique .dolfin). À partir des colonnes et d'un échantillon d'un jeu "
            "tabulaire, tu rédiges un modèle .dolfin de BROUILLON, fidèle au contenu du jeu. "
            "Réponds UNIQUEMENT par le contenu .dolfin (package + concepts), sans aucun texte ni "
            "balise markdown autour.\n\n" + DOLFIN_SYNTAX)
    usr = (f"Jeu : {pkg.get('title') or dataset}\n"
           f"Description : {(pkg.get('notes') or '')[:500] or '(aucune)'}\n"
           f"Colonnes : {json.dumps(cols, ensure_ascii=False)}\n"
           f"Échantillon de lignes : {json.dumps(sample, ensure_ascii=False)[:2500]}\n"
           "Rédige le modèle .dolfin complet.")
    raw = await llm.chat(sysp, usr, max_tokens=900, wait_s=90)
    txt = (raw or "").strip()
    if txt.startswith("```"):
        txt = txt.split("\n", 1)[-1]
        if txt.rstrip().endswith("```"):
            txt = txt.rstrip()[:-3]
    p = txt.find("package ")
    if p > 0:
        txt = txt[p:]
    txt = txt.strip()
    return {"dolfin": txt, "columns": cols,
            "title": pkg.get("title") or dataset,
            "type_suggestion": _dolfin_main_concept(txt)}


async def generate_chart(instance, dataset, intent=""):
    base = dict(config.directus_instances()).get(instance)
    if not base:
        raise ValueError(f"instance inconnue : {instance}")
    pkg, res, colinfo = await _resource_and_columns(dataset)
    if not res:
        raise ValueError("aucune ressource tabulaire (datastore) pour ce jeu")
    cols, sample = colinfo

    sysp = ("Tu es un expert en visualisation de données. On te donne les colonnes d'un jeu "
            "tabulaire et une intention. Propose la meilleure configuration de graphique. "
            "Réponds UNIQUEMENT par un objet JSON valide, sans texte. N'utilise que des noms "
            "de colonnes fournis. Schéma : {\"titre\":str, \"type\":un de "
            + str(CHART_TYPES) + ", \"colonne_x\":col, \"colonne_y\":col, "
            "\"colonne_serie\":col|null, \"agregation\":un de " + str(AGG) + ", \"unite\":str}.")
    usr = (f"Jeu : {pkg.get('title')}. Intention : {intent or 'graphique pertinent par défaut'}.\n"
           f"Colonnes : {json.dumps(cols, ensure_ascii=False)}\n"
           f"Échantillon : {json.dumps(sample, ensure_ascii=False)[:1500]}")
    raw = await llm.chat(sysp, usr, max_tokens=400, wait_s=90)
    a, b = raw.find("{"), raw.rfind("}")
    cfg = json.loads(raw[a:b + 1]) if a >= 0 and b > a else {}

    valid = set(cols)
    def keep(v):
        return v if (isinstance(v, str) and v in valid) else None
    item = {
        "titre": (cfg.get("titre") or pkg.get("title") or "Graphique")[:200],
        "dataset": res["id"],
        "type": cfg.get("type") if cfg.get("type") in CHART_TYPES else "bar",
        "colonne_x": keep(cfg.get("colonne_x")) or (cols[0] if cols else ""),
        "colonne_y": keep(cfg.get("colonne_y")) or (cols[1] if len(cols) > 1 else (cols[0] if cols else "")),
        "colonne_serie": keep(cfg.get("colonne_serie")),
        "agregation": cfg.get("agregation") if cfg.get("agregation") in AGG else "none",
        "unite": (cfg.get("unite") or "")[:40],
        # publié : un graphique draft est invisible au public ET en aperçu (rôle public
        # du portail = published only). La page qui l'embarque reste, elle, en brouillon.
        "status": "published",
    }
    headers = {"Content-Type": "application/json"}
    if config.DIRECTUS_TOKEN:
        headers["Authorization"] = f"Bearer {config.DIRECTUS_TOKEN}"
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.post(f"{base}/items/graphiques", headers=headers, json=item)
        r.raise_for_status()
        created = r.json().get("data") or {}
    log.info("graphique généré pour %s (instance %s) : id=%s", dataset, instance, created.get("id"))
    return {"id": created.get("id"), "titre": item["titre"], "type": item["type"],
            "colonne_x": item["colonne_x"], "colonne_y": item["colonne_y"], "dataset": dataset}


# Schéma de métadonnées par défaut (miroir de lib/metadata.js du portail), utilisé
# quand l'appelant n'envoie pas son propre schéma (ex. côté CKAN). Le portail, lui,
# transmet ses champs faisant autorité.
_THEMES = [
    'Administration et action publique', 'Agriculture',
    'Aménagement du territoire et urbanisme', 'Biodiversité et eau',
    'Citoyenneté et démocratie', 'Climat, air et énergie',
    'Culture, patrimoine et tourisme', 'Economie et entreprises',
    'Equipements, bâtiments et logements', 'Formation, éducation et emploi',
    'Mobilité et transports', 'Nuisances, déchets et risques',
    'Occupation des sols', 'Social, santé et sports',
]
_FREQ = ['Ponctuelle', 'Temps réel', 'Quotidienne', 'Hebdomadaire', 'Mensuelle',
         'Trimestrielle', 'Semestrielle', 'Annuelle', 'Pluriannuelle', 'Inconnue']
DEFAULT_META_FIELDS = [
    {"key": "sous_titre", "label": "Sous-titre", "type": "text"},
    {"key": "auteur", "label": "Auteur", "type": "text"},
    {"key": "producteur", "label": "Producteur", "type": "text"},
    {"key": "source", "label": "Source / origine des données", "type": "text"},
    {"key": "langue", "label": "Langue", "type": "select",
     "options": ["Français", "Anglais", "Multilingue", "Autre"]},
    {"key": "theme", "label": "Thématique", "type": "select", "options": _THEMES},
    {"key": "type_donnees", "label": "Type de données", "type": "select",
     "options": ["Données d'observation", "Données d'enquête", "Données administratives",
                 "Données de capteurs / mesures", "Référentiel", "Données géographiques",
                 "Données de simulation", "Autre"]},
    {"key": "frequence", "label": "Fréquence de mise à jour", "type": "select", "options": _FREQ},
    {"key": "couverture_spatiale", "label": "Couverture spatiale", "type": "text"},
    {"key": "couverture_temporelle", "label": "Couverture temporelle", "type": "text"},
]


async def generate_metadata(columns, sample, filename, fields):
    """Pré-remplissage de métadonnées au dépôt : à partir du nom de fichier, des
    colonnes et d'un échantillon (fournis par le client avant chargement datastore),
    propose titre, description, mots-clés et les champs de métadonnées demandés.
    `fields` = [{key,label,type,options?}]. Validation stricte des énumérations."""
    if not fields:
        fields = DEFAULT_META_FIELDS
    lignes = []
    for f in fields or []:
        if f.get("type") == "select" and f.get("options"):
            lignes.append(f"- {f['key']} ({f.get('label')}) : une valeur parmi "
                          f"{json.dumps(f['options'], ensure_ascii=False)} ou null")
        else:
            lignes.append(f"- {f['key']} ({f.get('label')}) : texte court ou null")
    sysp = ("Tu es un expert en métadonnées de données ouvertes (DCAT). À partir du nom de "
            "fichier, des colonnes et d'un échantillon, propose des métadonnées de qualité. "
            "Réponds UNIQUEMENT par un objet JSON valide, sans texte. Clés : \"titre\" (str, "
            "explicite et lisible), \"description\" (str, 2 à 3 phrases : contenu, maille, "
            "source probable), \"tags\" (liste de 3 à 8 mots-clés courts en minuscules), et "
            "pour chaque champ ci-dessous sa valeur (respecte STRICTEMENT les options fournies ; "
            "mets null si tu n'es pas sûr, n'invente pas) :\n" + "\n".join(lignes))
    usr = (f"Nom de fichier : {filename}\n"
           f"Colonnes : {json.dumps(columns, ensure_ascii=False)}\n"
           f"Échantillon : {json.dumps(sample, ensure_ascii=False)[:1800]}")
    raw = await llm.chat(sysp, usr, max_tokens=600, wait_s=60)
    a, b = raw.find("{"), raw.rfind("}")
    cfg = json.loads(raw[a:b + 1]) if a >= 0 and b > a else {}

    opts = {f["key"]: set(f.get("options") or []) for f in (fields or []) if f.get("type") == "select"}
    keys = {f["key"] for f in (fields or [])}
    extras = {}
    for k in keys:
        v = cfg.get(k)
        if v is None or not isinstance(v, (str, int, float)):
            continue
        v = str(v).strip()
        if not v:
            continue
        if k in opts and v not in opts[k]:
            continue  # énumération : rejette une valeur hors options
        extras[k] = v[:500]
    tags = cfg.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    tags = [str(t).strip()[:60] for t in tags if str(t).strip()][:8]
    return {"title": (cfg.get("titre") or "")[:200],
            "notes": (cfg.get("description") or "")[:1500],
            "tags": tags, "extras": extras}


DASH_AGG = ["sum", "wpop", "wmen", "wsup", "dens"]


async def generate_map(instance, dataset, intent=""):
    """Crée une carte choroplèthe : détecte le niveau territorial du jeu, le lie au
    contour de référence, et colore une valeur (colonne numérique). Écrit les items
    Directus `cartes` + `carte_couches` (brouillon)."""
    base = dict(config.directus_instances()).get(instance)
    if not base:
        raise ValueError(f"instance inconnue : {instance}")
    pkg, res, colinfo = await _resource_and_columns(dataset)
    if not res:
        raise ValueError("aucune ressource tabulaire (datastore) pour ce jeu")
    cols, sample = colinfo
    from . import territory
    terr = await territory.resolve(cols, sample)
    if not terr["linkable"]:
        raise ValueError("liaison territoriale impossible : aucune colonne de code territorial "
                         "(commune/EPCI/département/région) détectée dans ce jeu")
    code_col = terr["code_col"]

    # choix de la valeur à colorer : l'IA propose, repli = 1re colonne numérique
    row0 = sample[0] if sample else {}
    numeric = [c for c in cols if c != code_col and _isnum(row0.get(c))]
    valeur_col, titre = (numeric[0] if numeric else ""), pkg.get("title") or "Carte"
    try:
        raw = await llm.chat(
            "Tu proposes une carte choroplèthe. Réponds UNIQUEMENT en JSON "
            "{\"titre\":str, \"valeur_col\":une des colonnes numériques fournies}.",
            f"Jeu : {pkg.get('title')}. Intention : {intent or 'carte pertinente'}.\n"
            f"Colonnes numériques : {json.dumps(numeric, ensure_ascii=False)}\n"
            f"Échantillon : {json.dumps(sample[:2], ensure_ascii=False)[:1000]}", max_tokens=200, wait_s=60)
        a, b = raw.find("{"), raw.rfind("}")
        cfg = json.loads(raw[a:b + 1]) if a >= 0 and b > a else {}
        if cfg.get("valeur_col") in numeric:
            valeur_col = cfg["valeur_col"]
        if cfg.get("titre"):
            titre = cfg["titre"]
    except Exception:
        # GPU en démarrage ou réponse inexploitable : on garde le repli déterministe
        # (1re colonne numérique + titre du jeu), la liaison territoriale suffit.
        pass
    if not valeur_col:
        raise ValueError("aucune colonne numérique à cartographier dans ce jeu")

    headers = {"Content-Type": "application/json"}
    if config.DIRECTUS_TOKEN:
        headers["Authorization"] = f"Bearer {config.DIRECTUS_TOKEN}"
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.post(f"{base}/items/cartes", headers=headers,
                           json={"titre": titre[:200], "status": "published"})
        r.raise_for_status()
        carte_id = (r.json().get("data") or {}).get("id")
        await cli.post(f"{base}/items/carte_couches", headers=headers, json={
            "carte": carte_id, "label": f"{terr['niveau_label']} — {valeur_col}"[:120],
            "type": "choroplethe", "dataset": res["id"], "geojson_rid": terr["contour_rid"],
            "code_col": code_col, "geo_code_col": terr["geo_code_col"],
            "valeur_col": valeur_col, "visible": True, "activable": True})
    log.info("carte choroplèthe générée pour %s (instance %s) : id=%s, niveau=%s, valeur=%s",
             dataset, instance, carte_id, terr["level"], valeur_col)
    return {"id": carte_id, "titre": titre, "niveau": terr["level"],
            "valeur_col": valeur_col, "code_col": code_col, "dataset": dataset}


async def generate_dashboard(instance, dataset, intent=""):
    """Propose un tableau de bord (un niveau territorial + une liste d'indicateurs) à
    partir des colonnes d'un jeu, et crée les items Directus tableaux_bord + tb_niveaux
    + tb_indicateurs (statut brouillon)."""
    base = dict(config.directus_instances()).get(instance)
    if not base:
        raise ValueError(f"instance inconnue : {instance}")
    pkg, res, colinfo = await _resource_and_columns(dataset)
    if not res:
        raise ValueError("aucune ressource tabulaire (datastore) pour ce jeu")
    cols, sample = colinfo

    sysp = ("Tu es un expert en tableaux de bord territoriaux. On te donne les colonnes d'un "
            "jeu tabulaire et une intention. Propose UN niveau territorial et une liste "
            "d'indicateurs chiffrés pertinents. Réponds UNIQUEMENT par un objet JSON valide, "
            "sans texte. N'utilise que des noms de colonnes fournis. Schéma : {\"titre\":str, "
            "\"niveau\":{\"label\":str,\"code_colonne\":col}, \"indicateurs\":[{\"colonne\":col,"
            "\"libelle\":str,\"unite\":str,\"agregation\":un de " + str(DASH_AGG) + ","
            "\"cartographiable\":bool}]}. Au plus 6 indicateurs.")
    usr = (f"Jeu : {pkg.get('title')}. Intention : {intent or 'tableau de bord synthétique'}.\n"
           f"Colonnes : {json.dumps(cols, ensure_ascii=False)}\n"
           f"Échantillon : {json.dumps(sample, ensure_ascii=False)[:1500]}")
    raw = await llm.chat(sysp, usr, max_tokens=700, wait_s=120)
    a, b = raw.find("{"), raw.rfind("}")
    cfg = json.loads(raw[a:b + 1]) if a >= 0 and b > a else {}

    valid = set(cols)
    def keep(v):
        return v if (isinstance(v, str) and v in valid) else None

    niveau_cfg = cfg.get("niveau") or {}
    code_col = keep(niveau_cfg.get("code_colonne")) or (cols[0] if cols else "")
    # Liaison territoriale : détecte le niveau et le contour de référence à joindre.
    from . import territory
    terr = await territory.resolve(cols, sample)
    if terr["code_col"]:
        code_col = terr["code_col"]
    niveau_label = terr["niveau_label"] or niveau_cfg.get("label") or "Territoires"
    contour_rid = terr["contour_rid"] if terr["linkable"] else None
    indics = []
    for it in (cfg.get("indicateurs") or [])[:6]:
        col = keep(it.get("colonne"))
        if not col:
            continue
        indics.append({
            "colonne": col, "libelle": (it.get("libelle") or col)[:120],
            "unite": (it.get("unite") or "")[:40],
            "agregation": it.get("agregation") if it.get("agregation") in DASH_AGG else "sum",
            "cartographiable": bool(it.get("cartographiable")),
        })
    if not indics:  # repli : premières colonnes numériques de l'échantillon
        row0 = sample[0] if sample else {}
        for col in cols:
            if col == code_col:
                continue
            if _isnum(row0.get(col)):
                indics.append({"colonne": col, "libelle": col, "unite": "",
                               "agregation": "sum", "cartographiable": False})
            if len(indics) >= 4:
                break
    # si le jeu est joignable à un contour, rendre cartographiable au moins un indicateur
    if contour_rid and indics and not any(i["cartographiable"] for i in indics):
        indics[0]["cartographiable"] = True

    headers = {"Content-Type": "application/json"}
    if config.DIRECTUS_TOKEN:
        headers["Authorization"] = f"Bearer {config.DIRECTUS_TOKEN}"
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.post(f"{base}/items/tableaux_bord", headers=headers,
                           json={"titre": (cfg.get("titre") or pkg.get("title") or "Tableau de bord")[:200],
                                 "status": "published"})
        r.raise_for_status()
        tb_id = (r.json().get("data") or {}).get("id")
        niveau = {"tableau": tb_id, "label": niveau_label[:80],
                  "dataset": res["id"], "code_colonne": code_col}
        if contour_rid:
            niveau["contour"] = contour_rid  # liaison au contour de référence
            niveau["geo_code_colonne"] = terr["geo_code_col"]  # colonne code côté GeoJSON
        await cli.post(f"{base}/items/tb_niveaux", headers=headers, json=niveau)
        for ind in indics:
            await cli.post(f"{base}/items/tb_indicateurs", headers=headers,
                           json={"tableau": tb_id, **ind})
    log.info("tableau de bord généré pour %s (instance %s) : id=%s, %d indicateurs, niveau=%s, contour=%s",
             dataset, instance, tb_id, len(indics), terr["level"], bool(contour_rid))
    return {"id": tb_id, "titre": (cfg.get("titre") or pkg.get("title")),
            "niveau": terr["level"], "code_col": code_col, "contour_lie": bool(contour_rid),
            "indicateurs": [i["libelle"] for i in indics], "dataset": dataset}


async def _discover_datasets(description, limit=3):
    """Découvre les jeux les plus pertinents pour une description en langage naturel, via
    la recherche sémantique RAG (embeddings + qdrant, source CKAN). Renvoie une liste de
    noms de jeux (slugs), au plus `limit`. Vide si rien de pertinent."""
    if not description:
        return []
    from . import store
    try:
        vec = await llm.embed_one(description)
        if not vec:
            return []
        hits = await store.search(vec, limit=30,
                                  must=[{"key": "source", "match": {"value": "ckan"}}])
    except Exception as e:
        log.info("découverte de jeux (RAG) indisponible : %s", e)
        return []
    seen, out = set(), []
    for h in hits:
        name = (h.get("payload") or {}).get("dataset_name")
        if name and name not in seen:
            seen.add(name)
            out.append(name)
        if len(out) >= limit:
            break
    return out


async def _dataset_is_geo(dataset):
    """(pkg, joignable_à_un_contour) pour un jeu : sert à choisir carte vs graphique."""
    try:
        pkg, res, colinfo = await _resource_and_columns(dataset)
        if not res:
            return None, False
        cols, sample = colinfo
        from . import territory
        terr = await territory.resolve(cols, sample)
        return pkg, bool(terr.get("linkable"))
    except Exception:
        return None, False


async def generate_page(instance, datasets=None, intent=""):
    """Génère une PAGE brouillon à partir d'UN OU PLUSIEURS jeux et/ou d'une description.
    - `datasets` (liste de slugs) : les jeux à mettre en page. Si vide, ils sont
      DÉCOUVERTS depuis `intent` (description en langage naturel) via le RAG.
    - Pour chaque jeu : un bloc carte si le jeu est joignable à un contour, sinon un bloc
      graphique (réutilise les générateurs de composants). Plus un titre + une intro IA.
    Crée la page `pages` (draft) et ses `page_blocs`. Tolérant aux composants qui échouent."""
    base = dict(config.directus_instances()).get(instance)
    if not base:
        raise ValueError(f"instance inconnue : {instance}")
    datasets = [d for d in (datasets or []) if d]
    discovered = False
    if not datasets:
        datasets = await _discover_datasets(intent, limit=2)
        discovered = True
    if not datasets:
        raise ValueError("aucun jeu sélectionné, et aucun jeu pertinent trouvé pour cette "
                         "description : précisez la demande ou choisissez des jeux.")

    # Titres des jeux (pour le plan éditorial)
    titres = []
    for d in datasets[:6]:
        try:
            pkg = await _ckan("package_show", {"id": d})
            titres.append(pkg.get("title") or d)
        except Exception:
            titres.append(d)

    # Plan éditorial : titre de page + intro (repli déterministe si LLM indisponible)
    plan = {}
    try:
        raw = await llm.chat(
            "Tu es un chef de projet éditorial open data. À partir d'une demande et de la "
            "liste des jeux retenus, propose un TITRE de page court et explicite (PAS la "
            "reprise de la demande) et une introduction (2 à 3 paragraphes en markdown, qui "
            "présentent le sujet et les données). Réponds UNIQUEMENT en JSON : "
            "{\"titre\":str, \"intro\":str}.",
            f"Demande : {intent or 'page de présentation'}\n"
            f"Jeux retenus : {json.dumps(titres, ensure_ascii=False)}",
            max_tokens=800, wait_s=150)
        a, b = raw.find("{"), raw.rfind("}")
        plan = json.loads(raw[a:b + 1]) if a >= 0 and b > a else {}
    except llm.GpuWarming:
        # GPU en réveil : on N'écrit PAS une page au titre bâclé. On remonte le 503 pour
        # que l'appelant réessaie une fois le modèle chargé (titre/intro corrects).
        raise
    except Exception as e:
        log.info("page: plan IA indisponible (%s), repli", e)
    # Repli de titre : jamais la demande brute (slug illisible). On dérive des jeux.
    titre = (plan.get("titre") or (f"Analyse : {titres[0]}" if titres else "Nouvelle page"))[:200]
    intro = plan.get("intro") or intent or ""

    headers = {"Content-Type": "application/json"}
    if config.DIRECTUS_TOKEN:
        headers["Authorization"] = f"Bearer {config.DIRECTUS_TOKEN}"

    # Composition : un GRAPHIQUE par jeu + UNE carte de résumé (1er jeu géolocalisé).
    # « Rien ou tout » : si le GPU redevient indisponible EN COURS de génération d'un
    # graphique, on ne laisse pas une page à moitié faite. On supprime les composants
    # déjà créés et on remonte le 503 (aucune page n'est créée). Les autres erreurs
    # (jeu non graphable, etc.) n'interrompent pas : ce composant est simplement omis.
    comps, created = [], []  # created : (collection, id) pour rollback GPU
    first_geo = None

    async def _rollback():
        async with httpx.AsyncClient(timeout=30) as c:
            for coll, cid in created:
                try:
                    await c.delete(f"{base}/items/{coll}/{cid}", headers=headers)
                except Exception:
                    pass

    try:
        for d in datasets:
            _, is_geo = await _dataset_is_geo(d)
            if is_geo and first_geo is None:
                first_geo = d
            try:
                cid = (await generate_chart(instance, d, intent))["id"]
                comps.append(("graphique", cid)); created.append(("graphiques", cid))
            except llm.GpuWarming:
                raise
            except Exception as e:
                log.info("page: graphique %s ignoré (%s)", d, e)
        if first_geo:
            try:
                cid = (await generate_map(instance, first_geo, intent))["id"]
                comps.append(("carte", cid)); created.append(("cartes", cid))
            except llm.GpuWarming:
                raise
            except Exception as e:
                log.info("page: carte de résumé %s ignorée (%s)", first_geo, e)
    except llm.GpuWarming:
        await _rollback()
        raise
    async with httpx.AsyncClient(timeout=60) as cli:
        slug = base_slug = _slugify(titre)
        n = 1
        while n <= 20:
            chk = await cli.get(f"{base}/items/pages", headers=headers,
                                params={"filter[slug][_eq]": slug, "fields": "id", "limit": 1})
            if chk.status_code == 200 and not (chk.json().get("data") or []):
                break
            n += 1
            slug = f"{base_slug}-{n}"
        r = await cli.post(f"{base}/items/pages", headers=headers,
                           json={"title": titre, "slug": slug, "status": "draft",
                                 # on conserve la demande d'origine sur la page (copiable
                                 # dans Directus, réutilisable pour régénérer/ajuster)
                                 "prompt_ia": (intent or "")[:2000]})
        r.raise_for_status()
        page_id = (r.json().get("data") or {}).get("id")
        blocs = []
        if intro:
            blocs.append({"type": "texte", "titre": "", "texte": intro})
        # Photos : le générateur souverain n'a pas de banque d'images ; s'il en est
        # demandé, on prépare des EMPLACEMENTS image vides (invisibles tant que non
        # remplis) que l'admin complète dans l'éditeur. Honnête et prêt à l'emploi.
        if re.search(r"photo|image|illustr", intent or "", re.I):
            for _ in range(2):
                blocs.append({"type": "image", "titre": "", "legende": ""})
        for kind, cid in comps:
            blocs.append({"type": kind, "titre": "",
                          ("carte" if kind == "carte" else "graphique"): cid})
        for i, b in enumerate(blocs):
            b.update({"page": page_id, "sort": i + 1, "status": "published", "largeur": "pleine"})
            rb = await cli.post(f"{base}/items/page_blocs", headers=headers, json=b)
            rb.raise_for_status()
    log.info("page générée (instance %s) : id=%s slug=%s jeux=%s (découverts=%s) blocs=%s",
             instance, page_id, slug, datasets, discovered, [b["type"] for b in blocs])
    return {"page_id": page_id, "slug": slug, "titre": titre, "datasets": datasets,
            "datasets_decouverts": discovered, "blocs": [b["type"] for b in blocs]}


async def _columns_of(rid):
    """Colonnes + petit échantillon d'une ressource datastore précise."""
    info = await _ckan("datastore_search", {"resource_id": rid, "limit": 3})
    cols = [f["id"] for f in info.get("fields", []) if f.get("id") != "_id"]
    sample = [{k: v for k, v in rec.items() if k != "_id"} for rec in info.get("records", [])]
    return cols, sample


async def _col_max(rid, col):
    """Valeur maximale d'une colonne (borne haute d'une jauge), via tri décroissant du
    datastore. Renvoie None si non numérique -> jauge en auto-échelle."""
    try:
        r = await _ckan("datastore_search", {"resource_id": rid, "sort": f"{col} desc", "limit": 1})
        recs = r.get("records") or []
        v = recs[0].get(col) if recs else None
        m = float(str(v).replace(",", ".")) if v not in (None, "") else None
        if m and m > 0:
            return max(1, round(m * 1.05))  # champ entier côté Directus
    except Exception:
        pass
    return None


async def _propose_descriptor(numeric, sample):
    """Demande à l'IA le mode d'agrégation de chaque colonne (best-effort, sans attendre
    le réveil GPU : wait_s=0). Renvoie {colonne: mode} filtré, {} si indisponible."""
    try:
        raw = await llm.chat(
            "Tu classes des colonnes d'indicateurs COMMUNAUX selon leur mode d'agrégation "
            "vers un niveau supérieur (EPCI/département/région). Réponds UNIQUEMENT en JSON "
            "{\"colonne\":\"mode\"} où mode vaut \"sum\" (comptages, population, surfaces, "
            "montants totaux), \"wmean:population\" (taux, parts, pourcentages, médianes, "
            "ratios, indices : moyenne pondérée par la population) ou \"dens\" (densité de "
            "population uniquement). N'utilise que les colonnes fournies.",
            f"Colonnes : {json.dumps(numeric, ensure_ascii=False)}\n"
            f"Échantillon : {json.dumps(sample[:2], ensure_ascii=False)[:1000]}",
            max_tokens=500, wait_s=0)
        a, b = raw.find("{"), raw.rfind("}")
        d = json.loads(raw[a:b + 1]) if a >= 0 and b > a else {}
        out = {}
        for c, m in d.items():
            if c in numeric and isinstance(m, str) and (m in ("sum", "dens") or m.startswith("wmean:")):
                out[c] = m
        return out
    except Exception:
        return {}


async def generate_portrait(instance, dataset, intent="", target_level=None):
    """Génère un « PORTRAIT DE TERRITOIRE » : une page brouillon avec une CARTE choroplèthe
    PILOTE (un clic sur une zone sélectionne le territoire) et des JAUGES d'indicateurs
    RÉACTIVES (portée territoire) qui se filtrent automatiquement sur le territoire choisi,
    plus une intro rédigée.

    `target_level` (epci|departement|region) : si fourni ET que le jeu est COMMUNAL, on
    agrège d'abord vers ce niveau (ressource dérivée) et on bâtit le portrait dessus.
    Réutilise le socle « filtres liés » : carte `pilote_territoire=true` -> bus -> graphiques
    réactifs. Tolérant au GPU en démarrage (repli déterministe)."""
    base = dict(config.directus_instances()).get(instance)
    if not base:
        raise ValueError(f"instance inconnue : {instance}")
    pkg = await _ckan("package_show", {"id": dataset})
    _, res, colinfo = await _resource_and_columns(dataset)
    if not res:
        raise ValueError("aucune ressource tabulaire (datastore) pour ce jeu")
    rid = res["id"]
    cols, sample = colinfo
    from . import territory
    # Niveau cible demandé + jeu COMMUNAL -> on agrège d'abord (ressource dérivée) et on
    # bâtit le portrait dessus. Jeu non communal : target_level ignoré (niveau natif).
    agg_mirror = None  # (rid, titre) de la ressource dérivée à référencer dans jeux_de_donnees
    if target_level in ("epci", "departement", "region"):
        native, src_code, _ = territory.detect_level(cols, sample)
        if native == "commune":
            from . import aggregate
            # descripteur d'agrégation proposé par l'IA (si GPU chaud), complété au heuristique.
            srow = sample[0] if sample else {}
            src_numeric = [c for c in cols if c != src_code and _isnum(srow.get(c))]
            descriptor = await _propose_descriptor(src_numeric, sample)
            for c in src_numeric:
                descriptor.setdefault(c, aggregate._heuristic_mode(c))
            agg = await aggregate.aggregate_dataset(dataset, target_level,
                                                    descriptor=descriptor or None)
            rid = agg["resource_id"]
            cols, sample = await _columns_of(rid)
            agg_mirror = (rid, f"{pkg.get('title') or dataset} — agrégé par "
                          f"{aggregate.LEVEL_LABEL[target_level]}")
    terr = await territory.resolve(cols, sample)
    if not terr["linkable"]:
        raise ValueError("portrait impossible : aucun niveau territorial (commune / EPCI / "
                         "département / région) détecté dans ce jeu")
    code_col = terr["code_col"]
    row0 = sample[0] if sample else {}
    numeric = [c for c in cols if c != code_col and _isnum(row0.get(c))]
    if not numeric:
        raise ValueError("aucune colonne numérique pour construire des indicateurs")

    # Plan IA : titre + intro + colonne à cartographier + jauges. Repli déterministe.
    plan = {}
    try:
        raw = await llm.chat(
            "Tu conçois un « portrait de territoire » (une carte + des chiffres clés). On te "
            "donne les colonnes NUMÉRIQUES d'un jeu territorial. Propose un titre, une intro "
            "(2 paragraphes en markdown), la colonne à colorer sur la carte, et jusqu'à 6 "
            "indicateurs (jauges). Réponds UNIQUEMENT en JSON : {\"titre\":str,\"intro\":str,"
            "\"carte_col\":col,\"indicateurs\":[{\"colonne\":col,\"libelle\":str,\"unite\":str}]}. "
            "N'utilise que les colonnes fournies. Le portrait couvre TOUS les territoires de ce "
            "niveau : ne nomme JAMAIS un territoire en particulier dans le titre (les lignes de "
            "l'échantillon ne sont que des exemples).",
            f"Jeu : {pkg.get('title')}. Intention : {intent or 'portrait synthétique du territoire'}.\n"
            f"Colonnes numériques : {json.dumps(numeric, ensure_ascii=False)}\n"
            f"Échantillon : {json.dumps(sample[:2], ensure_ascii=False)[:1200]}",
            max_tokens=800, wait_s=120)
        a, b = raw.find("{"), raw.rfind("}")
        plan = json.loads(raw[a:b + 1]) if a >= 0 and b > a else {}
    except Exception as e:
        log.info("portrait: plan IA indisponible (%s), repli déterministe", e)

    def keepnum(v):
        return v if (isinstance(v, str) and v in numeric) else None
    titre = (plan.get("titre") or f"Portrait du territoire : {pkg.get('title') or dataset}")[:200]
    intro = plan.get("intro") or intent or ""
    carte_col = keepnum(plan.get("carte_col")) or numeric[0]
    indics = []
    for it in (plan.get("indicateurs") or [])[:6]:
        col = keepnum(it.get("colonne"))
        if col and col not in [i["colonne"] for i in indics]:
            indics.append({"colonne": col, "libelle": (it.get("libelle") or col)[:120],
                           "unite": (it.get("unite") or "")[:40]})
    if not indics:  # repli : premières colonnes numériques
        indics = [{"colonne": c, "libelle": c, "unite": ""} for c in numeric[:5]]

    headers = {"Content-Type": "application/json"}
    if config.DIRECTUS_TOKEN:
        headers["Authorization"] = f"Bearer {config.DIRECTUS_TOKEN}"
    created = []  # (collection, id) pour rollback en cas d'échec en cours

    async def _rollback():
        async with httpx.AsyncClient(timeout=30) as c:
            for coll, cid in reversed(created):
                try:
                    await c.delete(f"{base}/items/{coll}/{cid}", headers=headers)
                except Exception:
                    pass

    try:
        async with httpx.AsyncClient(timeout=60) as cli:
            # 0) Ressource dérivée (agrégation) : la référencer TOUT DE SUITE dans
            # jeux_de_donnees, sinon la relation FK graphiques.dataset échoue (le miroir
            # ne se synchronise que toutes les 3 min).
            if agg_mirror:
                arid, atitre = agg_mirror
                chk = await cli.get(f"{base}/items/jeux_de_donnees/{arid}", headers=headers)
                if chk.status_code != 200:
                    await cli.post(f"{base}/items/jeux_de_donnees", headers=headers, json={
                        "rid": arid, "titre": atitre[:200], "dataset_titre": pkg.get("title") or dataset,
                        "dataset_slug": pkg.get("name") or dataset, "format": "CSV",
                        "geo": False, "datastore": True})
            # 1) CARTE choroplèthe PILOTE de territoire (le clic diffuse la sélection).
            rc = await cli.post(f"{base}/items/cartes", headers=headers,
                                json={"titre": titre[:200], "status": "published",
                                      "pilote_territoire": True})
            rc.raise_for_status()
            carte_id = (rc.json().get("data") or {}).get("id")
            created.append(("cartes", carte_id))
            await cli.post(f"{base}/items/carte_couches", headers=headers, json={
                "carte": carte_id, "label": f"{terr['niveau_label']} — {carte_col}"[:120],
                "type": "choroplethe", "dataset": rid, "geojson_rid": terr["contour_rid"],
                "code_col": code_col, "geo_code_col": terr["geo_code_col"],
                "valeur_col": carte_col, "visible": True, "activable": True})
            # 2) JAUGES réactives (portée territoire) : une par indicateur clé.
            graph_ids = []
            for ind in indics:
                vmax = await _col_max(rid, ind["colonne"])  # borne fixe (sinon auto-échelle)
                g = {"titre": ind["libelle"][:200], "dataset": rid, "type": "gauge",
                     "portee": "territoire", "colonne_y": ind["colonne"], "code_colonne": code_col,
                     "unite": ind["unite"], "serie_temporelle": False, "agregation": "none",
                     "colonnes": json.dumps([{"col": ind["colonne"], "label": ind["libelle"]}],
                                            ensure_ascii=False),
                     "status": "published"}
                if vmax:
                    g["valeur_max"] = vmax
                rg = await cli.post(f"{base}/items/graphiques", headers=headers, json=g)
                rg.raise_for_status()
                gid = (rg.json().get("data") or {}).get("id")
                graph_ids.append(gid)
                created.append(("graphiques", gid))
            # BARRE DE COMPARAISON (portée globale, non réactive) : top territoires sur
            # l'indicateur cartographié, pour situer le territoire dans l'ensemble.
            nom_col = "nom" if "nom" in cols else code_col
            carte_lbl = next((i["libelle"] for i in indics if i["colonne"] == carte_col), carte_col)
            rb = await cli.post(f"{base}/items/graphiques", headers=headers, json={
                "titre": f"Comparaison des territoires : {carte_lbl}"[:200], "dataset": rid,
                "type": "bar", "portee": "global", "colonne_x": nom_col, "colonne_y": carte_col,
                "agregation": "none", "tri": "value", "limite": 12, "status": "published"})
            bar_id = (rb.json().get("data") or {}).get("id") if rb.status_code < 300 else None
            if bar_id:
                created.append(("graphiques", bar_id))
            # 3) PAGE : intro + carte pilote (pleine) + jauges (tiers) + barre de comparaison.
            slug = base_slug = _slugify(titre)
            n = 1
            while n <= 20:
                chk = await cli.get(f"{base}/items/pages", headers=headers,
                                    params={"filter[slug][_eq]": slug, "fields": "id", "limit": 1})
                if chk.status_code == 200 and not (chk.json().get("data") or []):
                    break
                n += 1
                slug = f"{base_slug}-{n}"
            rp = await cli.post(f"{base}/items/pages", headers=headers,
                                json={"title": titre, "slug": slug, "status": "draft",
                                      "prompt_ia": (intent or "")[:2000]})
            rp.raise_for_status()
            page_id = (rp.json().get("data") or {}).get("id")
            blocs = []
            if intro:
                blocs.append({"type": "texte", "titre": "", "texte": intro, "largeur": "pleine"})
            blocs.append({"type": "carte", "titre": "", "carte": carte_id, "largeur": "pleine"})
            for gid in graph_ids:
                blocs.append({"type": "graphique", "titre": "", "graphique": gid, "largeur": "tiers"})
            if bar_id:
                blocs.append({"type": "graphique", "titre": "", "graphique": bar_id, "largeur": "pleine"})
            for i, blk in enumerate(blocs):
                blk.update({"page": page_id, "sort": i + 1, "status": "published"})
                rb = await cli.post(f"{base}/items/page_blocs", headers=headers, json=blk)
                rb.raise_for_status()
    except Exception:
        await _rollback()
        raise
    log.info("portrait généré (instance %s) : page=%s slug=%s carte=%s jauges=%d niveau=%s",
             instance, page_id, slug, carte_id, len(graph_ids), terr["level"])
    return {"page_id": page_id, "slug": slug, "titre": titre, "carte_id": carte_id,
            "niveau": terr["level"], "indicateurs": [i["libelle"] for i in indics],
            "dataset": dataset}
