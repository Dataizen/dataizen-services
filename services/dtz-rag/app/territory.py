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


# Colonnes de contour à ne jamais prendre comme clé de jointure (géométrie brute).
_GEOMISH = {"wkt", "geometry", "geom", "the_geom", "geojson", "shape", "_geojson"}


def _niveau_local_label(title, col):
    """Libellé lisible d'un niveau local, depuis le titre du jeu de contours
    (« Contours des quartiers » -> « Quartiers »), à défaut depuis la colonne."""
    import re
    t = re.sub(r"(?i)^contours?\s+(des?|du|de\s+la|d')\s*", "", (title or "").strip()).strip()
    if t:
        return t[:1].upper() + t[1:]
    return (col or "territoire").replace("_", " ").capitalize()


async def resolve_local(columns, sample, org):
    """Résolution d'un niveau TERRITORIAL LOCAL (quartier, secteur, IRIS, zonage...) :
    cherche, dans l'org du jeu, un jeu de contours (GeoJSON) dont une propriété reprend
    les valeurs d'une colonne du jeu. Permet un portrait/choroplèthe sur un découpage
    propre à l'instance, comme le fait le tableau de bord territorial manuel.

    Renvoie {code_col, geo_code_col, contour_rid, contour_titre, niveau_label} ou None.
    Volontairement strict (toutes les valeurs de l'échantillon doivent exister côté
    contour) pour éviter les faux positifs sur une colonne de mesure."""
    if not org:
        return None
    # valeurs candidates du jeu (colonnes non géométriques, non vides)
    data_cands = {}
    for c in columns:
        if c.lower() in _GEOMISH:
            continue
        vals = {str(r.get(c)).strip() for r in sample if r.get(c) not in (None, "")}
        if len(vals) >= 2:
            data_cands[c] = vals
    if not data_cands:
        return None
    try:
        found = await gen._ckan("package_search",
                                {"fq": f"organization:{org} +res_format:GeoJSON", "rows": 20})
    except Exception:
        return None
    best = None
    for pkg in found.get("results", []):
        geo = next((r for r in pkg.get("resources", [])
                    if (r.get("format") or "").lower() == "geojson"), None)
        if not geo:
            continue
        # propriétés du contour : via le CSV dérivé (datastore, requêtable) de préférence
        csv = next((r for r in pkg.get("resources", [])
                    if r.get("datastore_active") and (r.get("format") or "").upper() == "CSV"), None)
        if not csv:
            continue
        try:
            info = await gen._ckan("datastore_search", {"resource_id": csv["id"], "limit": 1000})
        except Exception:
            continue
        ccols = [f["id"] for f in info.get("fields", []) if f.get("id") != "_id"]
        recs = info.get("records", [])
        cvals = {cc: {str(r.get(cc)).strip() for r in recs if r.get(cc) not in (None, "")}
                 for cc in ccols if cc.lower() not in _GEOMISH}
        for dc, dv in data_cands.items():
            for cc, cv in cvals.items():
                if len(cv) < 2:
                    continue
                # toutes les valeurs (échantillon) du jeu doivent exister côté contour
                if not dv <= cv:
                    continue
                score = len(dv) + (5 if dc.lower() == cc.lower() else 0)
                if not best or score > best["_score"]:
                    best = {"_score": score, "code_col": dc, "geo_code_col": cc,
                            "contour_rid": geo["id"], "contour_titre": pkg.get("title"),
                            "niveau_label": _niveau_local_label(pkg.get("title"), cc)}
    if best:
        best.pop("_score", None)
    return best


async def resolve(columns, sample, org=None):
    """Détection + résolution du contour. Renvoie un dict prêt à l'emploi.

    `org` (org CKAN du jeu) active, si aucun niveau administratif n'est détecté, la
    résolution d'un niveau LOCAL via un jeu de contours de la même org (voir resolve_local)."""
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
    elif org:
        # aucun niveau administratif : tenter un niveau LOCAL (contour de l'org)
        loc = await resolve_local(columns, sample, org)
        if loc:
            out.update(level="local", code_col=loc["code_col"],
                       geo_code_col=loc["geo_code_col"], contour_rid=loc["contour_rid"],
                       contour_titre=loc["contour_titre"], niveau_label=loc["niveau_label"])
    # liaison possible dès qu'on a une colonne de code et un contour : la jointure
    # asymétrique (données ≠ « code ») est désormais gérée par le moteur choroplèthe.
    out["linkable"] = bool(out["code_col"] and out["contour_rid"])
    return out
