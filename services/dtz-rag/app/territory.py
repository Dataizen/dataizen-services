# -*- coding: utf-8 -*-
"""Liaison territoriale : détecte le niveau (commune/EPCI/département/région) d'un
jeu depuis sa colonne de code, et résout le contour de référence à joindre (org
CKAN `referentiels`). La jointure choroplèthe se fait sur une colonne `code`
identique côté données et côté propriétés du GeoJSON (convention de la plateforme).

Réutilise la logique de `dtz/scripts/derive_territoires.py`."""
import logging

from . import gen

log = logging.getLogger("dtz-rag.territory")

# région INSEE -> départements couverts (repris de derive_territoires)
REGION_DEPTS = {
    "11": ["75", "77", "78", "91", "92", "93", "94", "95"],
    "24": ["18", "28", "36", "37", "41", "45"],
    "27": ["21", "25", "39", "58", "70", "71", "89", "90"],
    "28": ["14", "27", "50", "61", "76"],
    "32": ["02", "59", "60", "62", "80"],
    "44": ["08", "10", "51", "52", "54", "55", "57", "67", "68", "88"],
    "52": ["44", "49", "53", "72", "85"],
    "53": ["22", "29", "35", "56"],
    "75": ["16", "17", "19", "23", "24", "33", "40", "47", "64", "79", "86", "87"],
    "76": ["09", "11", "12", "30", "31", "32", "34", "46", "48", "65", "66", "81", "82"],
    "84": ["01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74"],
    "93": ["04", "05", "06", "13", "83", "84"],
    "94": ["2A", "2B"],
}
REGIONS = set(REGION_DEPTS)  # codes région (pour reconnaître un jeu au niveau région)
DEPT_TO_REGION = {d: r for r, ds in REGION_DEPTS.items() for d in ds}
# code région -> slug (aligné sur les jeux contours-<niveau>-<slug> créés)
REGION_SLUG = {
    "11": "ile-de-france", "24": "centre-val-de-loire", "27": "bourgogne-franche-comte",
    "28": "normandie", "32": "hauts-de-france", "44": "grand-est", "52": "pays-de-la-loire",
    "53": "bretagne", "75": "nouvelle-aquitaine", "76": "occitanie",
    "84": "auvergne-rhone-alpes", "93": "provence-alpes-cote-d-azur", "94": "corse",
}
_EPCI_REGION = None  # cache SIREN EPCI -> code région (chargé du référentiel EPCI)


def _dept_of(code):
    c = str(code).strip().upper()
    if c[:2] in ("2A", "2B"):
        return c[:2]
    if c[:2] in ("97", "98"):
        return c[:3]
    return c[:2] if len(c) >= 2 and c[:2].isdigit() else None

COLS_EPCI = ["code_epci", "siren_epci", "siren"]
COLS_COMMUNE = ["code_commune", "code_insee", "codgeo", "depcom", "insee_com", "insee", "com"]
COLS_DEPT = ["code_departement", "code_dept", "insee_dep", "dep", "departement"]
COLS_REGION = ["code_region", "insee_reg", "reg"]

# niveau -> jeu de contours de référence NATIONAL (repli si pas de contour par région).
# EPCI : pas de géométrie nationale ; couvert uniquement par les contours par région
# (contours-epci-<region>), donc pas de repli national.
CONTOUR_SLUGS = {
    "commune": "referentiel-communes-france",
    "departement": "referentiel-departements-france",
    "region": "referentiel-regions-france",
}
NIVEAU_LABEL = {"commune": "Communes", "epci": "EPCI",
                "departement": "Départements", "region": "Régions"}


def _infer_from_values(vals):
    v = [str(x).strip().upper() for x in vals if str(x).strip() not in ("", "NONE")][:80]
    if not v:
        return None
    if any(len(x) == 9 and x.isdigit() for x in v):
        return "epci"                              # SIREN 9 chiffres
    if all(x in REGIONS for x in v):
        return "region"
    if any(len(x) >= 4 for x in v):
        return "commune"                           # INSEE 5 (ou 2A/2B/97x)
    if all(len(x) <= 3 for x in v):
        return "departement"
    return None


def detect_level(columns, sample):
    """Renvoie (level, code_col, joinable). joinable = la colonne de jointure est
    « code » (nom identique côté contour), donc la choroplèthe se rend directement."""
    lower = {c.lower(): c for c in columns}
    code_col, level = None, None
    if "code" in lower:
        code_col = lower["code"]
        level = _infer_from_values([r.get(code_col) for r in sample])
    if not level:
        for lvl, cands in [("epci", COLS_EPCI), ("commune", COLS_COMMUNE),
                           ("departement", COLS_DEPT), ("region", COLS_REGION)]:
            for c in cands:
                if c in lower:
                    code_col, level = code_col or lower[c], lvl
                    break
            if level:
                break
    joinable = bool(code_col) and code_col.lower() == "code"
    return level, code_col, joinable


async def _epci_region_map():
    """SIREN EPCI -> code région, depuis le référentiel EPCI (mis en cache)."""
    global _EPCI_REGION
    if _EPCI_REGION is None:
        _EPCI_REGION = {}
        try:
            pkg = await gen._ckan("package_show", {"id": "referentiel-epci-france"})
            res = next((r for r in pkg.get("resources", [])
                        if (r.get("format") or "").upper() == "CSV" and "convert" not in (r.get("name") or "").lower()), None)
            if res:
                info = await gen._ckan("datastore_search", {"resource_id": res["id"], "limit": 2000})
                for rec in info.get("records", []):
                    code = rec.get("code_epci") or rec.get("code")
                    reg = rec.get("code_region")
                    if code and reg:
                        _EPCI_REGION[str(code)] = str(reg)
        except Exception:
            pass
    return _EPCI_REGION


async def _detect_region(level, code_col, sample):
    """Code région majoritaire d'un échantillon, selon le niveau."""
    vals = [str(r.get(code_col) or "").strip().upper() for r in sample if r.get(code_col)]
    if not vals:
        return None
    if level in ("commune",):
        regs = [DEPT_TO_REGION.get(_dept_of(v)) for v in vals]
    elif level == "epci":
        m = await _epci_region_map()
        regs = [m.get(v) for v in vals]
    elif level == "departement":
        regs = [DEPT_TO_REGION.get(v) for v in vals]
    else:
        return None
    regs = [r for r in regs if r]
    if not regs:
        return None
    return max(set(regs), key=regs.count)  # région majoritaire


async def _contour_rid(slug):
    """Résout le slug de contour en (rid GeoJSON, titre). None si absent."""
    try:
        pkg = await gen._ckan("package_show", {"id": slug})
    except Exception:
        return None, None
    res = next((r for r in pkg.get("resources", [])
                if (r.get("format") or "").lower() == "geojson"), None)
    return (res["id"] if res else None), pkg.get("title")


async def resolve(columns, sample):
    """Détection + résolution du contour. Renvoie un dict prêt à l'emploi."""
    level, code_col, joinable = detect_level(columns, sample)
    # geo_code_col = colonne de jointure côté contour (convention : toujours « code »).
    out = {"level": level, "code_col": code_col, "geo_code_col": "code",
           "joinable": joinable, "linkable": False,
           "contour_rid": None, "contour_titre": None, "niveau_label": None}
    if level:
        out["niveau_label"] = NIVEAU_LABEL.get(level)
        # préférer le contour PAR RÉGION s'il existe (communes/EPCI), sinon national
        region = await _detect_region(level, code_col, sample)
        out["region"] = region
        rid = titre = None
        prefix = {"commune": "contours-communes", "epci": "contours-epci"}.get(level)
        if prefix and region in REGION_SLUG:
            rid, titre = await _contour_rid(f"{prefix}-{REGION_SLUG[region]}")
        if not rid:
            slug = CONTOUR_SLUGS.get(level)
            if slug:
                rid, titre = await _contour_rid(slug)
        out["contour_rid"] = rid
        out["contour_titre"] = titre
    # liaison possible dès qu'on a une colonne de code et un contour : la jointure
    # asymétrique (données ≠ « code ») est désormais gérée par le moteur choroplèthe.
    out["linkable"] = bool(code_col and out["contour_rid"])
    return out
