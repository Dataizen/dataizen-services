# -*- coding: utf-8 -*-
"""Client qdrant (REST) pour la collection `dataizen_docs`. Upsert par id
déterministe, suppression par filtre (ré-indexation propre d'un jeu/d'une page),
recherche filtrée par périmètre/visibilité."""
import logging
import uuid

import httpx

from . import config

log = logging.getLogger("dtz-rag.store")

# Namespace stable pour dériver des ids de points déterministes.
_NS = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")

# Champs de payload indexés (filtrage rapide).
_KEYWORD_FIELDS = ["source", "org", "instance", "visibility", "doc_type", "dataset_name", "url"]


def point_id(*parts):
    return str(uuid.uuid5(_NS, "|".join(str(p) for p in parts)))


async def ensure_collection():
    """Crée la collection + les index de payload si absents (idempotent)."""
    async with httpx.AsyncClient(timeout=30) as cli:
        r = await cli.get(f"{config.QDRANT_URL}/collections/{config.QDRANT_COLLECTION}")
        if r.status_code == 404:
            await cli.put(
                f"{config.QDRANT_URL}/collections/{config.QDRANT_COLLECTION}",
                json={"vectors": {"size": config.EMBED_DIM, "distance": "Cosine"}})
            log.info("collection %s créée", config.QDRANT_COLLECTION)
        for field in _KEYWORD_FIELDS:
            await cli.put(
                f"{config.QDRANT_URL}/collections/{config.QDRANT_COLLECTION}/index",
                json={"field_name": field, "field_schema": "keyword"})


async def upsert(points):
    """points = [{'id','vector','payload'}]. Upsert (remplace par id)."""
    if not points:
        return
    async with httpx.AsyncClient(timeout=120) as cli:
        r = await cli.put(
            f"{config.QDRANT_URL}/collections/{config.QDRANT_COLLECTION}/points?wait=true",
            json={"points": points})
        r.raise_for_status()


async def delete_where(must):
    """Supprime tous les points dont le payload correspond au filtre `must`
    (liste de {'key','match':{'value'}})."""
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.post(
            f"{config.QDRANT_URL}/collections/{config.QDRANT_COLLECTION}/points/delete?wait=true",
            json={"filter": {"must": must}})
        r.raise_for_status()


async def existing_texts(must):
    """Renvoie {point_id: texte} des points existants correspondant au filtre.
    Sert à l'indexation INCRÉMENTALE : on ne ré-embed que les chunks dont le texte
    a changé (le texte est déjà stocké dans le payload, aucune migration requise)."""
    out, offset = {}, None
    async with httpx.AsyncClient(timeout=60) as cli:
        while True:
            body = {"filter": {"must": must}, "limit": 1000,
                    "with_payload": ["text"], "with_vector": False}
            if offset is not None:
                body["offset"] = offset
            r = await cli.post(
                f"{config.QDRANT_URL}/collections/{config.QDRANT_COLLECTION}/points/scroll",
                json=body)
            r.raise_for_status()
            res = r.json().get("result", {})
            for p in res.get("points", []):
                out[str(p["id"])] = (p.get("payload") or {}).get("text")
            offset = res.get("next_page_offset")
            if not offset:
                break
    return out


async def existing_payloads(must, keys):
    """Comme existing_texts mais renvoie {point_id: payload} restreint aux `keys`.
    Sert à l'indexation incrémentale ET au court-circuit par ressource : on récupère
    en une passe le texte (diff d'embedding) ET le tampon de version de ressource
    (`res_version`), pour sauter la re-pagination d'une ressource inchangée."""
    out, offset = {}, None
    async with httpx.AsyncClient(timeout=60) as cli:
        while True:
            body = {"filter": {"must": must}, "limit": 1000,
                    "with_payload": keys, "with_vector": False}
            if offset is not None:
                body["offset"] = offset
            r = await cli.post(
                f"{config.QDRANT_URL}/collections/{config.QDRANT_COLLECTION}/points/scroll",
                json=body)
            r.raise_for_status()
            res = r.json().get("result", {})
            for p in res.get("points", []):
                out[str(p["id"])] = p.get("payload") or {}
            offset = res.get("next_page_offset")
            if not offset:
                break
    return out


async def set_payload(ids, payload):
    """Met à jour le payload de points existants SANS toucher au vecteur (pas de
    réembedding). Sert à (re)poser le tampon `res_version` sur des chunks dont le
    texte n'a pas changé mais dont la version de ressource a bougé (ou est absente,
    ex. migration)."""
    if not ids:
        return
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.post(
            f"{config.QDRANT_URL}/collections/{config.QDRANT_COLLECTION}/points/payload?wait=true",
            json={"payload": payload, "points": list(ids)})
        r.raise_for_status()


async def delete_ids(ids):
    """Supprime des points par leurs ids (chunks disparus lors d'une réindexation)."""
    if not ids:
        return
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.post(
            f"{config.QDRANT_URL}/collections/{config.QDRANT_COLLECTION}/points/delete?wait=true",
            json={"points": list(ids)})
        r.raise_for_status()


async def search(vector, limit=8, must=None, should=None):
    """Recherche ANN filtrée. `must`/`should` = listes de conditions qdrant."""
    flt = {}
    if must:
        flt["must"] = must
    if should:
        flt["should"] = should
    body = {"vector": vector, "limit": limit, "with_payload": True}
    if flt:
        body["filter"] = flt
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.post(
            f"{config.QDRANT_URL}/collections/{config.QDRANT_COLLECTION}/points/search",
            json=body)
        r.raise_for_status()
        return r.json().get("result", [])


async def count():
    async with httpx.AsyncClient(timeout=30) as cli:
        r = await cli.post(
            f"{config.QDRANT_URL}/collections/{config.QDRANT_COLLECTION}/points/count",
            json={"exact": True})
        if r.status_code != 200:
            return None
        return r.json().get("result", {}).get("count")
