# -*- coding: utf-8 -*-
"""Indexation du contenu éditorial du CMS Directus (par instance) dans qdrant.
Lecture publique (contenu publié), une instance = un Directus. Les pages sont
indexées en fusionnant leurs blocs (page_blocs) pour un document complet."""
import logging

import httpx

from . import config, llm, parse, store

log = logging.getLogger("dtz-rag.cms")


async def _items(base, collection, params=None):
    p = {"filter[status][_eq]": "published", "limit": "-1"}
    if params:
        p.update(params)
    # Jeton de service : le rôle PUBLIC de Directus n'a pas la lecture au niveau CHAMP
    # sur certains contenus (ex. `content` des pages) -> un GET public renvoie 403 et les
    # pages n'étaient jamais indexées. On lit avec le jeton (mais on garde le filtre
    # `published` : v1 = contenu public uniquement).
    headers = {"Authorization": f"Bearer {config.DIRECTUS_TOKEN}"} if config.DIRECTUS_TOKEN else {}
    try:
        async with httpx.AsyncClient(timeout=60) as cli:
            r = await cli.get(f"{base}/items/{collection}", params=p, headers=headers)
            r.raise_for_status()
            return r.json().get("data") or []
    except Exception as e:
        log.warning("Directus %s/%s indisponible : %s", base, collection, e)
        return []


def _portal(instance):
    return f"https://{instance}.{config.PUBLIC_DOMAIN}"


async def _docs_for_instance(base, instance):
    """Construit (doc_type, item_id, title, url, updated, text) pour l'instance."""
    docs = []
    portal = _portal(instance)

    # NB : ne PAS demander `date_updated` : ce champ n'existe pas sur ces collections
    # (pages, page_blocs, actualites, reuses) et Directus renvoie alors 403 sur TOUTE la
    # requête -> plus aucune page indexée (le contexte de page de l'assistant tombait à
    # l'eau). On s'en passe (l'horodatage n'est pas indispensable en v1).
    pages = await _items(base, "pages",
                         {"fields": "id,title,slug,content"})
    blocs = await _items(base, "page_blocs",
                        {"fields": "page,titre,texte", "sort": "sort"})
    blocs_by_page = {}
    for b in blocs:
        blocs_by_page.setdefault(b.get("page"), []).append(b)
    for p in pages:
        parts = [p.get("title") or "", parse.strip_html(p.get("content"))]
        for b in blocs_by_page.get(p.get("id"), []):
            parts += [b.get("titre") or "", parse.strip_html(b.get("texte"))]
        text = "\n".join(x for x in parts if x).strip()
        if text:
            docs.append(("pages", p.get("id"), p.get("title") or p.get("slug"),
                         f"{portal}/pages/{p.get('slug')}", p.get("date_updated") or "", text))

    for a in await _items(base, "actualites",
                          {"fields": "id,title,chapo,content"}):
        text = "\n".join(x for x in [a.get("title"), a.get("chapo"),
                                     parse.strip_html(a.get("content"))] if x)
        if text:
            docs.append(("actualites", a.get("id"), a.get("title"),
                         f"{portal}/actualites/{a.get('id')}", a.get("date_updated") or "", text))

    for r in await _items(base, "reuses",
                          {"fields": "id,title,description,url"}):
        text = "\n".join(x for x in [r.get("title"), r.get("description"), r.get("url")] if x)
        if text:
            docs.append(("reuses", r.get("id"), r.get("title"),
                         f"{portal}/reutilisations", r.get("date_updated") or "", text))

    for t in await _items(base, "thematiques", {"fields": "id,title,description,slug"}):
        text = "\n".join(x for x in [t.get("title"), t.get("description")] if x)
        if text:
            docs.append(("thematiques", t.get("id"), t.get("title"),
                         f"{portal}/", "", text))

    for i in await _items(base, "indicateurs",
                          {"fields": "id,libelle,valeur,unite,source"}):
        text = " ".join(str(x) for x in [i.get("libelle"), i.get("valeur"),
                                         i.get("unite"), i.get("source")] if x)
        if text:
            docs.append(("indicateurs", i.get("id"), i.get("libelle"),
                         f"{portal}/", "", text))

    for h in await _items(base, "home_blocks", {"fields": "id,title,content"}):
        text = "\n".join(x for x in [h.get("title"), parse.strip_html(h.get("content"))] if x)
        if text:
            docs.append(("home_blocks", h.get("id"), h.get("title"),
                         f"{portal}/", "", text))
    return docs


async def index_instance(instance, base):
    docs = await _docs_for_instance(base, instance)
    must = [{"key": "source", "match": {"value": "cms"}},
            {"key": "instance", "match": {"value": instance}}]
    cibles = []
    for doc_type, item_id, title, url, updated, text in docs:
        for ci, ch in enumerate(parse.chunk(text)):
            pid = store.point_id("cms", instance, doc_type, item_id, ci)
            payload = {
                "source": "cms", "doc_type": doc_type, "org": "",
                "instance": instance, "visibility": "public", "dataset_name": "",
                "title": title, "url": url, "item_id": item_id,
                "updated_at": updated, "chunk": ci, "text": ch,
            }
            cibles.append((pid, ch, payload))
    if not cibles:
        await store.delete_where(must)
        return 0
    # INCRÉMENTAL (voir ckan_index) : ne (ré)embed que le nouveau/modifié.
    existants = await store.existing_texts(must)
    ids_courants = {c[0] for c in cibles}
    a_embed = [c for c in cibles if existants.get(c[0]) != c[1]]
    if a_embed:
        vectors = await llm.embed([c[1] for c in a_embed])
        await store.upsert([{"id": c[0], "vector": v, "payload": c[2]}
                            for c, v in zip(a_embed, vectors)])
    disparus = [pid for pid in existants if pid not in ids_courants]
    await store.delete_ids(disparus)
    log.info("CMS %s indexé : %d chunks (%d (ré)embed, %d inchangés, %d supprimés)",
             instance, len(cibles), len(a_embed), len(cibles) - len(a_embed), len(disparus))
    return len(a_embed)


async def index_all():
    total = 0
    for name, base in config.directus_instances():
        try:
            total += await index_instance(name, base)
        except Exception as e:
            log.warning("échec indexation CMS %s : %s", name, e)
    return total
