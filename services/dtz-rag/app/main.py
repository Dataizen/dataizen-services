# -*- coding: utf-8 -*-
"""API du service dtz-rag : indexation (webhooks de fraîcheur + réindexation
complète), recherche sémantique et réponse sourcée sur le catalogue CKAN et le
contenu CMS Directus. v1 : contenu public uniquement."""
import asyncio
import json
import logging

import httpx

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import (ckan_index, cms_index, config, dataset_usages, gen, llm, mailer,
               mcp_server, quality, scope, store, usage)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dtz-rag")

app = FastAPI(title="dtz-rag", version="0.1")


class Query(BaseModel):
    q: str
    scope: dict | None = None
    top_k: int = 8


@app.on_event("startup")
async def _startup():
    try:
        await store.ensure_collection()
    except Exception as e:  # ne bloque pas le démarrage si qdrant tarde
        log.warning("ensure_collection au démarrage : %s", e)
    # Suivi d'usage GPU : init DB + poller des sessions d'allumage (non bloquant).
    await usage.init()
    asyncio.create_task(usage.poll_loop())


@app.on_event("shutdown")
async def _shutdown():
    await usage.close()


@app.get("/healthz")
async def healthz():
    n = None
    try:
        n = await store.count()
    except Exception:
        pass
    return {"ok": True, "collection": config.QDRANT_COLLECTION, "points": n}


def _check_webhook(token):
    if not config.WEBHOOK_TOKEN or token != config.WEBHOOK_TOKEN:
        raise HTTPException(status_code=403, detail="jeton invalide")


def _gpu_base():
    """Base du gpu-controller askem-ai déduite de OLLAMA_URL (…/gpu/proxy -> …)."""
    url = config.OLLAMA_URL or ""
    return url.split("/gpu/proxy")[0] if "/gpu/proxy" in url else url.rstrip("/")


@app.get("/gpu/status")
async def gpu_status():
    """État du GPU souverain. PUBLIC (indicateur front + admin) : lecture seule."""
    base = _gpu_base()
    if not base:
        return {"available": False}
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            d = (await c.get(f"{base}/gpu/status")).json()
        return {
            "available": True,
            "instance_status": d.get("instance_status"),
            "ollama_ready": bool(d.get("ollama_ready")),
            "ollama_responding": bool(d.get("ollama_responding")),
            "model_loaded": bool(d.get("model_loaded")),
            "wake_in_progress": bool(d.get("wake_in_progress")),
            "idle_minutes": d.get("idle_minutes"),
            "billing_remaining_minutes": d.get("billing_remaining_minutes"),
        }
    except Exception as e:
        return {"available": False, "error": str(e)[:120]}


@app.post("/gpu/wake")
async def gpu_wake(x_dtz_token: str = Header(default=""),
                   x_dtz_instance: str = Header(default=""),
                   x_dtz_user: str = Header(default="")):
    """Démarre (réveille) le GPU souverain en arrière-plan. Protégé par jeton
    (le portail proxifie côté admin, en transmettant l'instance et l'email admin)."""
    _check_webhook(x_dtz_token)
    base = _gpu_base()
    if not base:
        raise HTTPException(status_code=503, detail="contrôleur GPU indisponible")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{base}/gpu/wake")
        await usage.record_event("réveil manuel", instance=x_dtz_instance or None,
                                 user_email=x_dtz_user or None)
        return {"started": True}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"réveil GPU échoué : {str(e)[:120]}")


# --- Passerelle OpenAI-compatible pour l'IA native de Directus (settings/ai) ---
# Directus (et tout client OpenAI-compat) parle à /v1/chat/completions. On traduit vers
# l'endpoint ollama NATIF avec think=false : c'est le SEUL moyen d'obtenir un contenu non
# vide de qwen3.5 (via l'OpenAI-compat de litellm/ollama, le modèle « raisonne » et renvoie
# un content vide). dtz-rag est interne au réseau dtz : Directus l'atteint en server-side.
@app.get("/v1/models")
async def openai_models():
    return {"object": "list", "data": [
        {"id": "dtz-souverain", "object": "model", "owned_by": "dataizen"}]}


def _flatten_content(c):
    """Le contenu d'un message OpenAI peut être une chaîne OU un tableau de « parts »
    (ex. [{"type":"text","text":"…"}]) : les clients récents (Vercel AI SDK, utilisé par
    l'assistant natif de Directus) envoient ce format. On aplatit vers du texte simple, seul
    format accepté par l'endpoint ollama natif."""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for p in c:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and p.get("type") in (None, "text") and p.get("text"):
                parts.append(p["text"])
        return "\n".join(parts)
    return ""


@app.post("/v1/chat/completions")
async def openai_chat(body: dict, authorization: str = Header(default="")):
    _check_webhook(authorization.replace("Bearer", "").strip())
    # On aplatit le contenu (chaîne ou tableau de parts) et on ignore les messages sans
    # texte (ex. appels d'outils : le shim ne gère pas le tool-calling, seulement le chat).
    messages = []
    for m in (body.get("messages") or []):
        if not m.get("role"):
            continue
        txt = _flatten_content(m.get("content"))
        if txt.strip():
            messages.append({"role": m["role"], "content": txt})
    if not messages:
        raise HTTPException(status_code=400, detail="messages requis")
    try:
        mt = max(64, min(int(body.get("max_tokens") or body.get("max_completion_tokens") or 800), 3000))
    except Exception:
        mt = 800
    temp = body.get("temperature")
    temp = 0.2 if temp is None else float(temp)
    try:
        content = await llm.chat_messages(messages, max_tokens=mt, temperature=temp, wait_s=150)
    except llm.GpuWarming:
        raise HTTPException(status_code=503, detail="Le GPU souverain démarre (1 à 3 min). Réessayez.")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"IA indisponible : {str(e)[:120]}")
    model = body.get("model") or "dtz-souverain"
    if body.get("stream"):
        def _sse():
            for delta in ({"role": "assistant", "content": content}, {}):
                fin = None if delta else "stop"
                chunk = {"id": "chatcmpl-dtz", "object": "chat.completion.chunk", "model": model,
                         "choices": [{"index": 0, "delta": delta, "finish_reason": fin}]}
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_sse(), media_type="text/event-stream")
    return {
        "id": "chatcmpl-dtz", "object": "chat.completion", "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@app.post("/reindex")
async def reindex(what: str = "all", x_dtz_token: str = Header(default="")):
    _check_webhook(x_dtz_token)

    async def _run():
        try:
            await store.ensure_collection()
            if what in ("all", "ckan"):
                await ckan_index.index_all()
            if what in ("all", "cms"):
                await cms_index.index_all()
        except Exception as e:
            log.error("réindexation complète échec : %s", e)

    asyncio.create_task(_run())
    return {"started": True, "what": what}


@app.post("/reindex/dataset/{name}")
async def reindex_dataset(name: str, x_dtz_token: str = Header(default="")):
    _check_webhook(x_dtz_token)
    n = await ckan_index.index_one(name)
    return {"dataset": name, "chunks": n}


@app.get("/dataset/usages/{name}")
async def dataset_usages_ep(name: str, x_dtz_token: str = Header(default="")):
    """Instances (portails) où le jeu est utilisé (graphiques, cartes, tableaux de bord).
    Index inverse balayé en direct sur le Directus de chaque instance."""
    _check_webhook(x_dtz_token)
    return await dataset_usages.usages_for_dataset(name)


@app.post("/mcp")
async def mcp_endpoint(request: Request, authorization: str = Header(default="")):
    """Serveur MCP (Model Context Protocol) : outils catalogue/RAG pour clients MCP
    (open-webui, agents). JSON-RPC 2.0, réponse application/json. Auth Bearer = jeton
    webhook. Interne au réseau dtz pour l'instant (exposition vRack/public = étape à part)."""
    _check_webhook(authorization.replace("Bearer", "").strip())
    body = await request.json()
    if isinstance(body, list):  # batch JSON-RPC
        resp = [r for r in [await mcp_server.dispatch(m) for m in body] if r is not None]
        return JSONResponse(resp) if resp else Response(status_code=202)
    resp = await mcp_server.dispatch(body)
    if resp is None:  # notification
        return Response(status_code=202)
    return JSONResponse(resp)


@app.post("/usages/stamp")
async def usages_stamp(sync: int = 0, x_dtz_token: str = Header(default="")):
    """Recalcule l'usage de tous les jeux publics et stampe les extras CKAN
    (usages_instances / usages_count), pour le filtre « Utilisation » du catalogue.
    Lourd : lancé en tâche de fond (sync=1 pour attendre le résultat, ex. test)."""
    _check_webhook(x_dtz_token)
    if sync:
        return await dataset_usages.stamp_all()
    asyncio.create_task(dataset_usages.stamp_all())
    return {"started": True}


@app.post("/reindex/cms/{instance}")
async def reindex_cms(instance: str, x_dtz_token: str = Header(default="")):
    _check_webhook(x_dtz_token)
    base = dict(config.directus_instances()).get(instance)
    if not base:
        raise HTTPException(status_code=404, detail="instance inconnue")
    n = await cms_index.index_instance(instance, base)
    return {"instance": instance, "chunks": n}


class GenChart(BaseModel):
    instance: str
    dataset: str | None = ""            # rétro-compat : un seul jeu
    datasets: list[str] | None = None   # multi-jeux (prioritaire sur `dataset`)
    intent: str | None = ""
    description: str | None = ""         # alias d'intention (UI de génération)
    level: str | None = ""               # portrait : niveau cible (epci|departement|region)


def _datasets_of(body):
    ds = [d for d in (body.datasets or []) if d]
    if not ds and body.dataset:
        ds = [body.dataset]
    return ds


def _intent_of(body):
    return (body.intent or body.description or "")


_KIND_LABEL = {"generate_chart": "génération graphique", "generate_map": "génération carte",
               "generate_dashboard": "génération tableau de bord"}


async def _batch(fn, instance, datasets, intent):
    """Applique un générateur de composant à chaque jeu. Tolérant : un jeu qui échoue
    (ex. pas de datastore, pas de géo) est reporté dans `errors`, sans bloquer les autres.
    Le réveil GPU (GpuWarming) est propagé pour que l'appelant réessaie."""
    await usage.record_event(_KIND_LABEL.get(fn.__name__, "génération"), instance=instance,
                             detail=(intent or None) and intent[:120])
    results, errors = [], []
    for d in datasets:
        try:
            results.append(await fn(instance, d, intent))
        except llm.GpuWarming:
            raise
        except Exception as e:
            errors.append({"dataset": d, "error": str(e)})
    return {"results": results, "errors": errors}


class GenMeta(BaseModel):
    columns: list
    sample: list | None = []
    filename: str | None = ""
    fields: list | None = []


class Notify(BaseModel):
    to: list
    subject: str
    text: str


@app.post("/notify")
async def notify(body: Notify, x_dtz_token: str = Header(default="")):
    _check_webhook(x_dtz_token)
    n = await asyncio.to_thread(mailer.send, body.to, body.subject[:200], body.text[:8000])
    return {"sent": n}


class ParcEvent(BaseModel):
    type: str
    instance: str | None = ""
    detail: str | None = ""


@app.post("/parc/event")
async def parc_event(body: ParcEvent, x_dtz_token: str = Header(default="")):
    """Journalise un événement de cycle de vie du parc (provisioning, suppression,
    compte, email). Alimente la timeline de la page instance de la forge."""
    _check_webhook(x_dtz_token)
    await usage.record_parc_event(body.type, instance=body.instance or None,
                                  detail=body.detail or None)
    return {"ok": True}


@app.post("/quality")
async def quality_report(body: dict, x_dtz_token: str = Header(default="")):
    _check_webhook(x_dtz_token)
    name = (body or {}).get("dataset")
    if not name:
        raise HTTPException(status_code=400, detail="dataset requis")
    return await quality.compute(name)


@app.post("/generate/metadata")
async def generate_metadata(body: GenMeta, x_dtz_token: str = Header(default="")):
    _check_webhook(x_dtz_token)
    try:
        return await gen.generate_metadata(body.columns, body.sample or [],
                                           body.filename or "", body.fields or [])
    except llm.GpuWarming:
        raise HTTPException(status_code=503, detail="Le GPU démarre, réessayez dans une minute.")


class GenDolfin(BaseModel):
    dataset: str


@app.post("/dolfin/model")
async def generate_dolfin_model(body: GenDolfin, x_dtz_token: str = Header(default="")):
    """Brouillon de modèle canonique .dolfin (IA) à partir d'un jeu. L'appelant (portail)
    l'enregistre ensuite via l'action CKAN dolfin_model_save (compilation + versionnage)."""
    _check_webhook(x_dtz_token)
    if not (body.dataset or "").strip():
        raise HTTPException(status_code=400, detail="aucun jeu fourni")
    await usage.record_event("génération modèle DOLFIN", detail=body.dataset[:120])
    try:
        return await gen.generate_dolfin_model(body.dataset.strip())
    except llm.GpuWarming:
        raise HTTPException(status_code=503, detail="Le GPU démarre, réessayez dans une minute.")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/generate/chart")
async def generate_chart(body: GenChart, x_dtz_token: str = Header(default="")):
    _check_webhook(x_dtz_token)
    ds = _datasets_of(body)
    if not ds:
        raise HTTPException(status_code=400, detail="aucun jeu fourni")
    try:
        return await _batch(gen.generate_chart, body.instance, ds, _intent_of(body))
    except llm.GpuWarming:
        raise HTTPException(status_code=503, detail="Le GPU démarre, réessayez dans une minute.")


@app.post("/generate/dashboard")
async def generate_dashboard(body: GenChart, x_dtz_token: str = Header(default="")):
    _check_webhook(x_dtz_token)
    ds = _datasets_of(body)
    if not ds:
        raise HTTPException(status_code=400, detail="aucun jeu fourni")
    try:
        return await _batch(gen.generate_dashboard, body.instance, ds, _intent_of(body))
    except llm.GpuWarming:
        raise HTTPException(status_code=503, detail="Le GPU démarre, réessayez dans une minute.")


@app.post("/generate/map")
async def generate_map(body: GenChart, x_dtz_token: str = Header(default="")):
    _check_webhook(x_dtz_token)
    ds = _datasets_of(body)
    if not ds:
        raise HTTPException(status_code=400, detail="aucun jeu fourni")
    try:
        return await _batch(gen.generate_map, body.instance, ds, _intent_of(body))
    except llm.GpuWarming:
        raise HTTPException(status_code=503, detail="Le GPU démarre, réessayez dans une minute.")


@app.post("/generate/page")
async def generate_page(body: GenChart, x_dtz_token: str = Header(default="")):
    """Génère une page brouillon à partir d'un ou plusieurs jeux ET/OU d'une description.
    Si aucun jeu n'est fourni, les jeux sont découverts depuis la description via le RAG.
    Chaque jeu donne un bloc (carte si géo, sinon graphique) ; plus un titre + intro IA."""
    _check_webhook(x_dtz_token)
    intent = _intent_of(body)
    await usage.record_event("génération page", instance=body.instance,
                             detail=(intent or None) and intent[:120])
    try:
        return await gen.generate_page(body.instance, _datasets_of(body), intent)
    except llm.GpuWarming:
        raise HTTPException(status_code=503, detail="Le GPU démarre, réessayez dans une minute.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/generate/portrait")
async def generate_portrait(body: GenChart, x_dtz_token: str = Header(default="")):
    """Génère un « portrait de territoire » : page brouillon avec une carte choroplèthe
    PILOTE + des jauges d'indicateurs RÉACTIVES (clic sur la carte -> chiffres filtrés).
    Un seul jeu territorial ; si plusieurs sont fournis/découverts, on prend le premier
    exploitable (avec une colonne de code commune/EPCI/département/région)."""
    _check_webhook(x_dtz_token)
    intent = _intent_of(body)
    ds = _datasets_of(body) or await gen._discover_datasets(intent, limit=4)
    if not ds:
        raise HTTPException(status_code=400, detail="aucun jeu fourni, et aucun jeu pertinent "
                            "trouvé pour cette description.")
    await usage.record_event("génération portrait", instance=body.instance,
                             detail=(intent or None) and intent[:120])
    errors = []
    for d in ds[:4]:
        try:
            return await gen.generate_portrait(body.instance, d, intent,
                                               target_level=(body.level or None))
        except llm.GpuWarming:
            raise HTTPException(status_code=503, detail="Le GPU démarre, réessayez dans une minute.")
        except ValueError as e:
            errors.append(f"{d} : {e}")
    raise HTTPException(status_code=400, detail="aucun jeu territorial exploitable parmi les jeux "
                        "fournis (il faut une colonne de code commune/EPCI/département/région). "
                        + " ; ".join(errors))


@app.post("/aggregate")
async def aggregate_ep(body: dict, x_dtz_token: str = Header(default="")):
    """Agrège un jeu COMMUNAL au niveau cible (epci|departement|region) et crée une
    ressource dérivée (datastore) sur le jeu source. Réutilise une dérivée existante
    sauf force=1."""
    _check_webhook(x_dtz_token)
    from . import aggregate
    dataset = (body or {}).get("dataset")
    level = (body or {}).get("level")
    if not dataset or not level:
        raise HTTPException(status_code=400, detail="dataset et level requis")
    try:
        return await aggregate.aggregate_dataset(dataset, level, force=bool((body or {}).get("force")))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/territory/detect")
async def territory_detect(body: dict, x_dtz_token: str = Header(default="")):
    _check_webhook(x_dtz_token)
    name = (body or {}).get("dataset")
    if not name:
        raise HTTPException(status_code=400, detail="dataset requis")
    from . import territory
    _, res, colinfo = await gen._resource_and_columns(name)
    if not res:
        return {"level": None, "message": "aucune ressource tabulaire chargée"}
    cols, sample = colinfo
    return await territory.resolve(cols, sample)


async def _retrieve(q, sc, top_k):
    vec = await llm.embed_one(q)
    if vec is None:
        return []
    must, should = scope.build(sc)
    sc = sc or {}
    focus_ds = sc.get("focus_dataset")
    focus_url = sc.get("focus_url")
    focused = []
    # l'utilisateur consulte une page : on remonte d'abord le contenu de CETTE page
    if focus_ds:
        fmust = must + [{"key": "source", "match": {"value": "ckan"}},
                        {"key": "dataset_name", "match": {"value": focus_ds}}]
        focused = await store.search(vec, limit=8, must=fmust)
    elif focus_url:
        fmust = must + [{"key": "url", "match": {"value": focus_url}}]
        focused = await store.search(vec, limit=8, must=fmust)
    for h in focused:
        h["_focus"] = True
    general = await store.search(vec, limit=top_k, must=must, should=should)
    seen, merged = set(), []
    for h in focused + general:  # page/jeu courant en tête, marqué _focus
        hid = h.get("id")
        if hid in seen:
            continue
        seen.add(hid)
        merged.append(h)
    return merged[: top_k + (8 if focused else 0)]


def _sources(hits):
    seen, out = set(), []
    for h in hits:
        p = h.get("payload") or {}
        url = p.get("url")
        if url and url not in seen:
            seen.add(url)
            out.append({"title": p.get("title"), "url": url, "source": p.get("source")})
    return out


@app.post("/search")
async def search(query: Query):
    hits = await _retrieve(query.q, query.scope, query.top_k)
    return {"hits": [{"score": h.get("score"),
                      "title": (h.get("payload") or {}).get("title"),
                      "url": (h.get("payload") or {}).get("url"),
                      "source": (h.get("payload") or {}).get("source"),
                      "text": (h.get("payload") or {}).get("text")} for h in hits]}


SYS = ("Tu es l'assistant du portail de données ouvertes Dataizen. Réponds en "
       "français, de façon concise et factuelle, en t'appuyant UNIQUEMENT sur les "
       "extraits fournis. Cite les sources par leur titre. Si l'information ne "
       "figure pas dans les extraits, dis-le clairement sans inventer.")


@app.post("/answer")
async def answer(query: Query):
    await usage.record_event("assistant", instance=(query.scope or {}).get("instance"),
                             detail=(query.q or "")[:120])
    hits = await _retrieve(query.q, query.scope, query.top_k)
    if not hits:
        return {"answer": "Je n'ai trouvé aucune donnée pertinente dans le catalogue "
                          "pour cette question.", "sources": []}
    def fmt(hs, start=1):
        return "\n\n".join(
            f"[{i}] {(h.get('payload') or {}).get('title')} "
            f"({(h.get('payload') or {}).get('url')})\n{(h.get('payload') or {}).get('text')}"
            for i, h in enumerate(hs, start))

    focus_hits = [h for h in hits if h.get("_focus")]
    other_hits = [h for h in hits if not h.get("_focus")][:3]
    if focus_hits:
        # ancrage explicite : on nomme la page/jeu consulté et on base la réponse dessus
        cur_title = (focus_hits[0].get("payload") or {}).get("title") or "élément consulté"
        parts = [f"L'utilisateur consulte actuellement « {cur_title} ». Réponds à sa question "
                 f"en te basant PRINCIPALEMENT sur les extraits de CET élément ci-dessous. "
                 f"N'affirme jamais que l'élément consulté serait un autre ; ne mentionne les "
                 f"autres extraits que s'ils sont directement pertinents.",
                 f"\nQuestion : {query.q}",
                 "\nExtraits de l'élément consulté :\n" + fmt(focus_hits)]
        if other_hits:
            parts.append("\nAutres extraits du catalogue (contexte) :\n"
                         + fmt(other_hits, start=len(focus_hits) + 1))
        user = "\n".join(parts)
    else:
        user = f"Question : {query.q}\n\nExtraits :\n" + fmt(hits)
    try:
        ans = await llm.chat(SYS, user)
    except llm.GpuWarming:
        return JSONResponse(status_code=503, content={
            "warming": True,
            "message": "L'IA démarre le GPU (première requête, 1 à 2 min). Réessayez dans une minute.",
            "sources": _sources(hits)})
    return {"answer": ans, "sources": _sources(hits)}
