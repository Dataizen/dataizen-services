# -*- coding: utf-8 -*-
"""Agrégation ascendante d'un jeu COMMUNAL vers EPCI / département / région, publiée
comme RESSOURCE DÉRIVÉE sur le jeu source (datastore), à la manière des sorties DOLFIN.

- Correspondance commune -> EPCI/dép/région + population : référentiel-communes-france.
- Règle d'agrégation par colonne : somme (défaut), moyenne pondérée par la population
  (taux, parts, ratios, médianes), ou densité = somme(pop)/somme(superficie). Une IA peut
  proposer le descripteur ; sinon heuristique sur le nom de colonne.
- La ressource dérivée porte `code` (code du territoire cible) + `nom` + les indicateurs +
  `communes` (nombre de communes agrégées), et un marqueur `aggregated_level`.
"""
import logging

import httpx

from . import config, gen

log = logging.getLogger("dtz-rag.aggregate")

LEVEL_KEY = {"epci": "code_epci", "departement": "code_departement", "region": "code_region"}
LEVEL_LABEL = {"epci": "EPCI", "departement": "département", "region": "région"}

_COMMUNE_MAP = None   # code_insee -> enregistrement référentiel (code_epci, dept, region, population…)
_EPCI_NOM = None      # code_epci -> nom
_REGION_NOM = {  # code région INSEE -> nom (métropole + DROM)
    "11": "Île-de-France", "24": "Centre-Val de Loire", "27": "Bourgogne-Franche-Comté",
    "28": "Normandie", "32": "Hauts-de-France", "44": "Grand Est", "52": "Pays de la Loire",
    "53": "Bretagne", "75": "Nouvelle-Aquitaine", "76": "Occitanie",
    "84": "Auvergne-Rhône-Alpes", "93": "Provence-Alpes-Côte d'Azur", "94": "Corse",
    "01": "Guadeloupe", "02": "Martinique", "03": "Guyane", "04": "La Réunion", "06": "Mayotte",
}


def _num(v):
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        return None


async def _all_rows(rid, page=5000):
    """Toutes les lignes d'une ressource datastore (paginé)."""
    rows, offset = [], 0
    while True:
        info = await gen._ckan("datastore_search", {"resource_id": rid, "limit": page, "offset": offset})
        recs = info.get("records") or []
        rows.extend(recs)
        offset += len(recs)
        if len(recs) < page:
            break
    return rows


async def _commune_map():
    global _COMMUNE_MAP
    if _COMMUNE_MAP is None:
        _COMMUNE_MAP = {}
        try:
            pkg = await gen._ckan("package_show", {"id": "referentiel-communes-france"})
            res = next((r for r in pkg.get("resources", []) if r.get("datastore_active")), None)
            if res:
                for r in await _all_rows(res["id"]):
                    code = str(r.get("code_insee") or "").strip().upper()
                    if code:
                        _COMMUNE_MAP[code] = r
        except Exception as e:
            log.warning("aggregate: référentiel communes indisponible (%s)", e)
    return _COMMUNE_MAP


async def _epci_nom():
    global _EPCI_NOM
    if _EPCI_NOM is None:
        _EPCI_NOM = {}
        try:
            pkg = await gen._ckan("package_show", {"id": "referentiel-epci-france"})
            res = next((r for r in pkg.get("resources", []) if r.get("datastore_active")), None)
            if res:
                for r in await _all_rows(res["id"]):
                    c = str(r.get("code_epci") or "").strip()
                    if c and r.get("nom"):
                        _EPCI_NOM[c] = r["nom"]
        except Exception:
            pass
    return _EPCI_NOM


def _heuristic_mode(col):
    """Mode d'agrégation par défaut d'après le nom de colonne."""
    c = col.lower()
    if c in ("densite", "densité"):
        return "dens"
    if any(k in c for k in ("taux", "part_", "_pct", "pct", "median", "médian", "moyen",
                            "moyenne", "ratio", "indice", "pour_", "%")):
        return "wmean:population"
    return "sum"


def _agrege(rows, descriptor):
    out = {"communes": len(rows)}
    for col, mode in descriptor.items():
        if mode == "sum":
            out[col] = round(sum(v for v in (_num(r.get(col)) for r in rows) if v is not None), 3)
        elif mode == "dens":
            pop = sum(_num(r.get("population")) or 0 for r in rows)
            sup = sum(_num(r.get("superficie_km2")) or 0 for r in rows)
            out[col] = round(pop / sup, 1) if sup else None
        elif mode.startswith("wmean:"):
            poids = mode.split(":", 1)[1]
            n, d = 0.0, 0.0
            for r in rows:
                v, w = _num(r.get(col)), _num(r.get(poids))
                if v is not None and w:
                    n += v * w
                    d += w
            out[col] = round(n / d, 2) if d else None
        else:
            out[col] = None
    return out


async def _nom_of(level, code, cmap):
    if level == "region":
        return _REGION_NOM.get(str(code).zfill(2), code)
    if level == "departement":
        # nom du département : première commune du référentiel portant ce dép (repli = code)
        return code
    if level == "epci":
        return (await _epci_nom()).get(str(code), code)
    return code


async def _existing_derived(pkg, level):
    """Ressource dérivée déjà présente pour ce niveau (réutilisation), ou None."""
    for r in pkg.get("resources", []):
        if str(r.get("aggregated_level") or "") == level:
            return r.get("id")
    return None


async def _create_derived_resource(pkg, source_rid, level, fields, records):
    """Crée (ou remplace) la ressource dérivée datastore sur le jeu source."""
    headers = {"Authorization": config.CKAN_TOKEN, "Content-Type": "application/json"} \
        if config.CKAN_TOKEN else {}
    name = f"{pkg.get('title') or pkg.get('name')} — agrégé par {LEVEL_LABEL[level]}"
    async with httpx.AsyncClient(timeout=120) as cli:
        # datastore_create avec un `resource` inline crée la ressource ET son datastore.
        body = {"resource": {"package_id": pkg["id"], "name": name[:250], "format": "CSV",
                             "aggregated_level": level, "aggregated_from": source_rid},
                "fields": fields, "records": records, "primary_key": ["code"], "force": True}
        r = await cli.post(f"{config.CKAN_URL}/api/3/action/datastore_create",
                           json=body, headers=headers)
        r.raise_for_status()
        return (r.json().get("result") or {}).get("resource_id")


async def aggregate_dataset(dataset, target_level, descriptor=None, force=False):
    """Agrège un jeu communal au niveau cible et crée la ressource dérivée. Renvoie
    {resource_id, level, territoires, descriptor}. Réutilise une dérivée existante sauf
    si force=True."""
    if target_level not in LEVEL_KEY:
        raise ValueError("niveau cible invalide (epci | departement | region)")
    pkg, res, colinfo = await gen._resource_and_columns(dataset)
    if not res:
        raise ValueError("aucune ressource tabulaire (datastore) pour ce jeu")
    cols, sample = colinfo
    from . import territory
    level, code_col, _ = territory.detect_level(cols, sample)
    if level != "commune":
        raise ValueError(f"agrégation possible seulement depuis un jeu COMMUNAL "
                         f"(niveau détecté : {level or 'inconnu'})")
    if not force:
        existing = await _existing_derived(pkg, target_level)
        if existing:
            return {"resource_id": existing, "level": target_level, "territoires": None,
                    "reused": True}

    rows = await _all_rows(res["id"])
    if not rows:
        raise ValueError("jeu communal vide")
    # colonnes numériques à agréger (hors code)
    row0 = sample[0] if sample else {}
    numeric = [c for c in cols if c != code_col and _num(row0.get(c)) is not None]
    if not numeric:
        raise ValueError("aucune colonne numérique à agréger")
    # enrichissement commune -> EPCI/dép/région + population/superficie via le référentiel
    cmap = await _commune_map()
    for r in rows:
        code = str(r.get(code_col) or "").strip().upper()
        ref = cmap.get(code) or {}
        for k in ("code_epci", "code_departement", "code_region"):
            if not r.get(k):
                r[k] = ref.get(k)
        if _num(r.get("population")) is None and ref.get("population") is not None:
            r["population"] = ref.get("population")
        if _num(r.get("superficie_km2")) is None and ref.get("superficie_km2") is not None:
            r["superficie_km2"] = ref.get("superficie_km2")
    # descripteur d'agrégation (heuristique si non fourni)
    if not descriptor:
        descriptor = {c: _heuristic_mode(c) for c in numeric}
    # groupement + agrégation
    key = LEVEL_KEY[target_level]
    groups = {}
    for r in rows:
        k = str(r.get(key) or "").strip()
        if k:
            groups.setdefault(k, []).append(r)
    if not groups:
        raise ValueError("aucune correspondance territoriale trouvée (code EPCI/dép/région "
                         "absent et non résolu par le référentiel communes)")
    records = []
    for code, grp in groups.items():
        rec = {"code": code, "nom": await _nom_of(target_level, code, cmap)}
        rec.update(_agrege(grp, descriptor))
        records.append(rec)
    fields = ([{"id": "code", "type": "text"}, {"id": "nom", "type": "text"}]
              + [{"id": c, "type": "numeric"} for c in descriptor]
              + [{"id": "communes", "type": "int"}])
    rid = await _create_derived_resource(pkg, res["id"], target_level, fields, records)
    log.info("agrégation %s -> %s : %d territoires, ressource=%s", dataset, target_level,
             len(records), rid)
    return {"resource_id": rid, "level": target_level, "territoires": len(records),
            "descriptor": descriptor, "reused": False}
