# -*- coding: utf-8 -*-
"""Contrôle qualité d'un jeu de données au dépôt : contrôles déterministes
(fichier chargé, remplissage des colonnes, doublons, complétude des métadonnées)
+ suggestions d'amélioration par l'IA (best-effort). La partie déterministe
fonctionne même si le GPU est en démarrage."""
import json
import logging

import httpx

from . import config, llm

log = logging.getLogger("dtz-rag.quality")


async def _ckan(action, params):
    headers = {"Authorization": config.CKAN_TOKEN} if config.CKAN_TOKEN else {}
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.get(f"{config.CKAN_URL}/api/3/action/{action}", params=params, headers=headers)
        r.raise_for_status()
        return r.json()["result"]


def _chk(key, label, status, detail=""):
    return {"key": key, "label": label, "status": status, "detail": detail}


async def compute(dataset):
    pkg = await _ckan("package_show", {"id": dataset})
    ex = {e["key"]: e.get("value") for e in pkg.get("extras", [])}
    checks = []

    # --- Métadonnées ---
    title = (pkg.get("title") or "").strip()
    checks.append(_chk("titre", "Titre explicite", "ok" if len(title) >= 10 else "warn",
                       "" if len(title) >= 10 else "titre court ou absent"))
    notes = (pkg.get("notes") or "").strip()
    checks.append(_chk("description", "Description",
                       "ok" if len(notes) >= 80 else ("warn" if len(notes) >= 20 else "ko"),
                       f"{len(notes)} caractères" if notes else "aucune description"))
    tags = pkg.get("tags") or []
    checks.append(_chk("mots_cles", "Mots-clés", "ok" if len(tags) >= 3 else ("warn" if tags else "ko"),
                       f"{len(tags)} mot(s)-clé(s)"))
    lic = pkg.get("license_id") or ""
    checks.append(_chk("licence", "Licence renseignée",
                       "ok" if lic and lic != "notspecified" else "warn",
                       pkg.get("license_title") or "non spécifiée"))
    for key, label in [("point_de_contact", "Point de contact"), ("auteur", "Auteur"),
                       ("theme", "Thématique"), ("producteur", "Producteur")]:
        checks.append(_chk(key, label, "ok" if (ex.get(key) or "").strip() else "warn",
                           "" if (ex.get(key) or "").strip() else "à renseigner"))
    couv = (ex.get("couverture_temporelle") or ex.get("couverture_spatiale")
            or ex.get("territoires") or "").strip()
    checks.append(_chk("couverture", "Couverture (spatiale/temporelle)",
                       "ok" if couv else "warn", "" if couv else "aucune couverture indiquée"))

    # --- Données (datastore) ---
    res = next((r for r in pkg.get("resources", [])
                if r.get("datastore_active") and not r.get("harmonized_from")), None)
    fields, records = [], []
    if not res:
        checks.append(_chk("fichier", "Fichier chargé (datastore)", "warn",
                           "aucune ressource tabulaire chargée (patientez le chargement, ou format non tabulaire)"))
    else:
        try:
            info = await _ckan("datastore_search", {"resource_id": res["id"], "limit": 200})
        except Exception:
            info = {}
        fields = [f["id"] for f in info.get("fields", []) if f.get("id") != "_id"]
        records = [{k: v for k, v in r.items() if k != "_id"} for r in info.get("records", [])]
        checks.append(_chk("fichier", "Fichier chargé (datastore)", "ok",
                           f"{len(fields)} colonnes, échantillon de {len(records)} lignes"))
        # taux de remplissage par colonne
        if records:
            faibles = []
            for c in fields:
                rempli = sum(1 for r in records if str(r.get(c, "")).strip() not in ("", "None"))
                if rempli / len(records) < 0.5:
                    faibles.append(f"{c} ({round(100 * rempli / len(records))}%)")
            checks.append(_chk("remplissage", "Colonnes bien remplies",
                               "ok" if not faibles else "warn",
                               "" if not faibles else "peu remplies : " + ", ".join(faibles[:6])))
            # doublons dans l'échantillon
            seen, dups = set(), 0
            for r in records:
                t = tuple(sorted((k, str(v)) for k, v in r.items()))
                if t in seen:
                    dups += 1
                seen.add(t)
            checks.append(_chk("doublons", "Absence de doublons (échantillon)",
                               "ok" if dups == 0 else "warn",
                               "" if dups == 0 else f"{dups} ligne(s) dupliquée(s) dans l'échantillon"))

    total = len(checks)
    ok = sum(1 for c in checks if c["status"] == "ok")
    score = round(100 * ok / total) if total else 0

    suggestions, warming = await _ai_suggestions(pkg, fields, records, checks)
    return {"score": score, "checks": checks, "suggestions": suggestions, "warming": warming}


async def _ai_suggestions(pkg, fields, records, checks):
    faibles = [c["label"] for c in checks if c["status"] in ("warn", "ko")]
    sysp = ("Tu es un expert qualité des données ouvertes. À partir des métadonnées, des colonnes "
            "et d'un échantillon, donne 3 à 6 suggestions d'amélioration CONCRÈTES et actionnables "
            "pour la personne qui dépose (nommage de colonnes, unités, description, couverture, "
            "licence, complétude…). Réponds UNIQUEMENT par un tableau JSON de chaînes en français.")
    usr = (f"Titre : {pkg.get('title')}\nDescription : {(pkg.get('notes') or '')[:400]}\n"
           f"Colonnes : {json.dumps(fields, ensure_ascii=False)}\n"
           f"Échantillon : {json.dumps(records[:3], ensure_ascii=False)[:1200]}\n"
           f"Points faibles détectés : {json.dumps(faibles, ensure_ascii=False)}")
    try:
        raw = await llm.chat(sysp, usr, max_tokens=500)
    except llm.GpuWarming:
        return [], True
    a, b = raw.find("["), raw.rfind("]")
    try:
        arr = json.loads(raw[a:b + 1]) if a >= 0 and b > a else []
    except Exception:
        arr = []
    return [str(s)[:300] for s in arr if str(s).strip()][:6], False
