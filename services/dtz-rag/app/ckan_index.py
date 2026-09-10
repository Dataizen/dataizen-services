# -*- coding: utf-8 -*-
"""Indexation du catalogue CKAN dans qdrant : par jeu public, on produit
des documents (métadonnées, schéma des ressources, échantillon de lignes,
fichiers non tabulaires via docling), on les embed et on les upsert.

v1 : jeux PUBLICS uniquement (aucune donnée privée indexée)."""
import logging

import httpx

from . import config, llm, parse, store

log = logging.getLogger("dtz-rag.ckan")

# Extras à inclure dans le document de métadonnées (aligné METADATA_FIELDS du portail).
META_EXTRAS = [
    ("sous_titre", "Sous-titre"), ("theme", "Thème"), ("type_donnees", "Type de données"),
    ("territoires", "Territoires"), ("couverture_spatiale", "Couverture spatiale"),
    ("couverture_temporelle", "Couverture temporelle"), ("frequence", "Fréquence"),
    ("producteur", "Producteur"), ("auteur", "Auteur"), ("source", "Source"),
    ("point_de_contact", "Point de contact"), ("publication_associee", "Publication associée"),
    ("dolfin_profile", "Profil DOLFIN"),
]


async def _ckan(action, params):
    headers = {"Authorization": config.CKAN_TOKEN} if config.CKAN_TOKEN else {}
    async with httpx.AsyncClient(timeout=90) as cli:
        r = await cli.get(f"{config.CKAN_URL}/api/3/action/{action}",
                          params=params, headers=headers)
        r.raise_for_status()
        d = r.json()
    if not d.get("success"):
        raise RuntimeError(f"CKAN {action} échec")
    return d["result"]


def _fiche_url(name):
    return f"{config.CKAN_PUBLIC_URL}/dataset/{name}"


def _extras(pkg):
    return {e["key"]: e.get("value") for e in (pkg.get("extras") or [])}


def _metadata_text(pkg):
    ex = _extras(pkg)
    lines = [f"Jeu de données : {pkg.get('title') or pkg.get('name')}"]
    if pkg.get("notes"):
        lines.append(f"Description : {pkg['notes']}")
    org = (pkg.get("organization") or {}).get("title")
    if org:
        lines.append(f"Organisation : {org}")
    tags = [t.get("display_name") or t.get("name") for t in (pkg.get("tags") or [])]
    if tags:
        lines.append("Mots-clés : " + ", ".join(tags))
    for key, label in META_EXTRAS:
        if ex.get(key):
            lines.append(f"{label} : {ex[key]}")
    fmts = sorted({(r.get("format") or "").upper() for r in pkg.get("resources", []) if r.get("format")})
    if fmts:
        lines.append("Formats disponibles : " + ", ".join(fmts))
    return "\n".join(lines)


def _res_stamp(res, total=None):
    """Tampon de version bon marché d'une ressource, pour sauter la re-pagination si
    rien n'a bougé. last_modified est parfois None (ressource jamais rechargée) : on
    retombe sur created. Pour le datastore on ajoute le nombre de lignes (total, obtenu
    gratuitement via limit:0) : ça capte les ajouts/suppressions de lignes. Les éditions
    de valeurs en place sans changement de last_modified/total restent couvertes par les
    webhooks (qui forcent la reconstruction) et par une passe force=True."""
    base = res.get("last_modified") or res.get("created") or ""
    return f"{base}|{total}" if total is not None else str(base)


async def _resource_docs(pkg, res_versions, force=False):
    """Docs de contenu par ressource : schéma (colonnes) + échantillon tabulaire,
    ou extraction docling pour un fichier non tabulaire.

    COURT-CIRCUIT : si le tampon de version d'une ressource est inchangé (et qu'on a
    déjà ses chunks), on la SAUTE sans re-paginer ses milliers de lignes ni re-télécharger
    le fichier. Renvoie (docs, skipped_rids) ; docs = liste de (doc_type, rid, rname,
    texte, res_version). `force=True` désactive le court-circuit (webhook, passe complète)."""
    docs, skipped = [], set()
    for res in pkg.get("resources", []):
        if res.get("harmonized_from"):
            continue  # sortie dérivée : on indexe la source
        rid = res.get("id")
        fmt = (res.get("format") or "").lower()
        rname = res.get("name") or rid
        if res.get("datastore_active"):
            try:
                info = await _ckan("datastore_search", {"resource_id": rid, "limit": 0})
            except Exception:
                continue
            ver = _res_stamp(res, info.get("total"))
            if not force and rid in res_versions and res_versions[rid] == ver:
                skipped.add(rid)  # ressource inchangée : on garde ses chunks tels quels
                continue
            fields = [f["id"] for f in info.get("fields", []) if f.get("id") != "_id"]
            if fields:
                docs.append(("schema", rid, rname,
                             f"Ressource « {rname} » ({fmt or 'tabulaire'}). "
                             f"Colonnes : {', '.join(fields)}.", ver))
            # Contenu tabulaire complet (paginé, borné par INDEX_MAX_ROWS).
            rows, got, offset, total = [], 0, 0, None
            while config.INDEX_MAX_ROWS and got < config.INDEX_MAX_ROWS:
                page_sz = min(1000, config.INDEX_MAX_ROWS - got)
                try:
                    # tri par _id : ordre DÉTERMINISTE entre deux réindexations (sans
                    # ORDER BY, Postgres renvoie les lignes dans un ordre arbitraire, qui
                    # change au fil des mises à jour/VACUUM ; le texte concaténé varierait
                    # donc à chaque run et déclencherait un réémbedding inutile de tous les
                    # chunks tabulaires). Fiabilise aussi la pagination par offset.
                    page = await _ckan("datastore_search",
                                       {"resource_id": rid, "limit": page_sz,
                                        "offset": offset, "sort": "_id"})
                except Exception:
                    break
                recs = page.get("records") or []
                total = page.get("total", total)
                if not recs:
                    break
                for rec in recs:
                    cells = [f"{k}={v}" for k, v in rec.items()
                             if k != "_id" and k not in config.SKIP_ROW_COLS
                             and not isinstance(v, (dict, list)) and v not in (None, "")]
                    if cells:
                        rows.append("; ".join(cells))
                got += len(recs)
                offset += len(recs)
                if len(recs) < page_sz:
                    break
            if rows:
                trunc = ""
                if total and got < total:
                    trunc = f" (échantillon des {got} premières lignes sur {total})"
                    log.info("jeu %s ressource %s : %d/%d lignes indexées (tronqué)",
                             pkg.get("name"), rid, got, total)
                docs.append(("rows", rid, rname,
                             f"Données de « {rname} »{trunc} — colonnes : {', '.join(fields)}.\n"
                             + "\n".join(rows), ver))
        elif fmt in ("pdf", "docx", "doc", "odt", "rtf", "pptx", "ppt", "html", "htm"):
            ver = _res_stamp(res)  # fichier : tampon sur last_modified/created
            if not force and rid in res_versions and res_versions[rid] == ver:
                skipped.add(rid)  # document inchangé : pas de re-téléchargement/docling
                continue
            text = await _download_and_extract(res)
            if text:
                docs.append(("file", rid, rname, f"Document « {rname} » :\n{text}", ver))
    return docs, skipped


async def _download_and_extract(res):
    url = res.get("url")
    if not url:
        return ""
    try:
        headers = {"Authorization": config.CKAN_TOKEN} if config.CKAN_TOKEN else {}
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as cli:
            r = await cli.get(url, headers=headers)
            r.raise_for_status()
            content = r.content
        return await parse.docling_extract(content, res.get("name") or "document")
    except Exception:
        return ""


async def index_dataset(pkg, force=False):
    """Indexe un jeu (dict package_show). Ignore et purge si privé/supprimé.

    `force=True` : reconstruit tout, sans court-circuit par ressource (webhook, où l'on
    SAIT que la ressource a changé). `force=False` (filet complet) : les ressources dont
    le tampon de version n'a pas bougé sont sautées (pas de re-pagination)."""
    name = pkg.get("name")
    if not name:
        return 0
    must = [{"key": "source", "match": {"value": "ckan"}},
            {"key": "dataset_name", "match": {"value": name}}]
    if pkg.get("private") or pkg.get("state") == "deleted":
        await store.delete_where(must)
        log.info("jeu %s privé/supprimé -> retiré de l'index", name)
        return 0

    org = (pkg.get("organization") or {}).get("name") or ""
    url = _fiche_url(name)
    title = pkg.get("title") or name
    updated = pkg.get("metadata_modified") or ""

    # État actuel de l'index (texte pour le diff d'embedding, res_version pour le
    # court-circuit par ressource) récupéré en une seule passe.
    existants = await store.existing_payloads(must, ["text", "resource_id", "res_version"])
    res_versions = {}
    for pid, p in existants.items():
        rid = p.get("resource_id")
        if rid:
            res_versions.setdefault(rid, p.get("res_version"))

    docs = [("metadata", "", title, _metadata_text(pkg), updated)]
    rdocs, skipped = await _resource_docs(pkg, res_versions, force=force)
    docs += rdocs

    # Cible : (pid, texte, payload, res_version) pour chaque chunk (re)construit.
    cibles = []
    for doc_type, rid, rname, text, ver in docs:
        for ci, ch in enumerate(parse.chunk(text)):
            pid = store.point_id("ckan", name, doc_type, rid, ci)
            payload = {
                "source": "ckan", "doc_type": doc_type, "org": org,
                "instance": "", "visibility": "public", "dataset_name": name,
                "title": title, "url": url, "resource_id": rid,
                "updated_at": updated, "chunk": ci, "text": ch, "res_version": ver,
            }
            cibles.append((pid, ch, payload, ver))
    if not cibles and not skipped:
        await store.delete_where(must)
        return 0
    ids_courants = {c[0] for c in cibles}
    # Chunks des ressources SAUTÉES : à préserver (ni ré-embed, ni suppression).
    kept = {pid for pid, p in existants.items() if p.get("resource_id") in skipped}

    # INCRÉMENTAL : on ne (ré)embed que les chunks nouveaux ou dont le texte a changé.
    a_embed = [c for c in cibles if existants.get(c[0], {}).get("text") != c[1]]
    embed_ids = {c[0] for c in a_embed}
    if a_embed:
        vectors = await llm.embed([c[1] for c in a_embed])
        await store.upsert([{"id": c[0], "vector": v, "payload": c[2]}
                            for c, v in zip(a_embed, vectors)])
    # Chunks au texte INCHANGÉ mais dont le tampon res_version a bougé (ou est absent,
    # ex. migration) : on repose juste le tampon, SANS réembedding (set_payload).
    a_stamp = {}
    for c in cibles:
        if c[0] in embed_ids:
            continue
        if existants.get(c[0], {}).get("res_version") != c[3]:
            a_stamp.setdefault(c[3], []).append(c[0])
    for ver, ids in a_stamp.items():
        await store.set_payload(ids, {"res_version": ver})

    disparus = [pid for pid in existants if pid not in ids_courants and pid not in kept]
    await store.delete_ids(disparus)
    log.info("jeu %s indexé : %d chunks (%d (ré)embed, %d inchangés, %d ressources sautées, %d supprimés)",
             name, len(cibles), len(a_embed), len(cibles) - len(a_embed), len(skipped), len(disparus))
    return len(a_embed)


async def index_one(name, force=True):
    # Webhook / réindexation ciblée : on force (on sait que le jeu a changé).
    pkg = await _ckan("package_show", {"id": name})
    return await index_dataset(pkg, force=force)


async def index_all():
    """Parcourt tous les jeux publics et les indexe."""
    total, start, rows = 0, 0, 50
    while True:
        res = await _ckan("package_search",
                          {"q": "*:*", "fq": "+capacity:public", "rows": rows, "start": start})
        results = res.get("results", [])
        if not results:
            break
        for pkg in results:
            try:
                total += await index_dataset(pkg)
            except Exception as e:
                log.warning("échec indexation %s : %s", pkg.get("name"), e)
        start += rows
        if start >= res.get("count", 0):
            break
    log.info("indexation CKAN terminée : %d chunks", total)
    return total
