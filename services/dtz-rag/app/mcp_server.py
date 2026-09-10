# -*- coding: utf-8 -*-
"""Serveur MCP (Model Context Protocol) minimal : expose le catalogue et le RAG Dataizen
comme OUTILS pour des clients MCP (open-webui, IDE, agents).

Transport : JSON-RPC 2.0 sur HTTP (POST /mcp), réponse application/json (mode
requête/réponse, sans SSE ; suffisant pour des outils synchrones). Méthodes gérées :
initialize, notifications/initialized, ping, tools/list, tools/call.

Outils : catalogue_search, rag_search, dataset_get, answer. Périmètre PUBLIC uniquement."""
import logging

from . import ckan_index, config, llm, scope, store

log = logging.getLogger("dtz-rag.mcp")

PROTOCOL = "2024-11-05"
SERVER = {"name": "dataizen-catalog", "version": "1"}
_SYS = ("Tu es l'assistant du portail de données ouvertes Dataizen. Réponds en français, "
        "de façon concise et factuelle, en t'appuyant UNIQUEMENT sur les extraits fournis. "
        "Cite les sources par leur titre. Si l'information n'y figure pas, dis-le sans inventer.")

TOOLS = [
    {"name": "catalogue_search",
     "description": "Recherche des jeux de données publics du catalogue Dataizen par mots-clés. "
                    "Renvoie titre, description, organisation et lien de fiche.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "mots-clés de recherche"},
         "limit": {"type": "integer", "description": "nombre de résultats (défaut 10)"}},
         "required": ["query"]}},
    {"name": "rag_search",
     "description": "Recherche sémantique dans le contenu indexé (métadonnées et lignes des "
                    "jeux, pages éditoriales des portails). Renvoie des extraits sourcés.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"},
         "instance": {"type": "string", "description": "limiter au périmètre d'une instance (optionnel)"},
         "limit": {"type": "integer", "description": "nombre d'extraits (défaut 6)"}},
         "required": ["query"]}},
    {"name": "dataset_get",
     "description": "Détails d'un jeu de données (métadonnées, ressources, colonnes) par son "
                    "identifiant (slug).",
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string", "description": "slug du jeu, ex. equipements-bpe-points-bfc"}},
         "required": ["name"]}},
    {"name": "answer",
     "description": "Répond à une question en langage naturel à partir du catalogue et du "
                    "contenu Dataizen, avec sources (RAG). Le GPU souverain peut mettre 1 à 3 min "
                    "à démarrer à la première question de la journée.",
     "inputSchema": {"type": "object", "properties": {
         "question": {"type": "string"},
         "instance": {"type": "string", "description": "périmètre d'une instance (optionnel)"}},
         "required": ["question"]}},
]


async def _retrieve(q, sc, top_k=6):
    vec = await llm.embed_one(q)
    if not vec:
        return []
    must, should = scope.build(sc)
    return await store.search(vec, limit=top_k, must=must, should=should)


def _fiche(name):
    return f"{config.CKAN_PUBLIC_URL}/dataset/{name}"


async def _t_catalogue_search(query="", limit=10):
    n = max(1, min(int(limit or 10), 25))
    res = await ckan_index._ckan("package_search",
                                 {"q": query or "*:*", "fq": "+capacity:public", "rows": n})
    lignes = []
    for p in res.get("results", []):
        org = (p.get("organization") or {}).get("title") or ""
        lignes.append(f"- {p.get('title') or p.get('name')} — {(p.get('notes') or '')[:180]}\n"
                      f"  organisation : {org} · {_fiche(p.get('name'))}")
    return (f"{res.get('count', 0)} jeu(x) trouvé(s) :\n" + "\n".join(lignes)) if lignes \
        else "Aucun jeu de données ne correspond."


async def _t_rag_search(query, instance="", limit=6):
    sc = {"instance": instance} if instance else None
    hits = await _retrieve(query, sc, top_k=max(1, min(int(limit or 6), 12)))
    if not hits:
        return "Aucun extrait pertinent trouvé."
    out = []
    for h in hits:
        p = h.get("payload") or {}
        out.append(f"• {p.get('title')} — {p.get('url')}\n{(p.get('text') or '')[:400]}")
    return "\n\n".join(out)


async def _t_dataset_get(name):
    pkg = await ckan_index._ckan("package_show", {"id": name})
    lines = [f"Jeu : {pkg.get('title') or pkg.get('name')} ({pkg.get('name')})",
             f"Organisation : {(pkg.get('organization') or {}).get('title') or '—'}"]
    if pkg.get("notes"):
        lines.append(f"Description : {pkg['notes'][:500]}")
    res = pkg.get("resources", [])
    lines.append(f"Ressources ({len(res)}) : "
                 + ", ".join(f"{r.get('name')} [{(r.get('format') or '?')}]" for r in res[:20]))
    lines.append(f"Lien : {_fiche(pkg.get('name'))}")
    return "\n".join(lines)


async def _t_answer(question, instance=""):
    sc = {"instance": instance} if instance else None
    hits = await _retrieve(question, sc, top_k=6)
    if not hits:
        return "Aucune donnée pertinente trouvée dans le catalogue Dataizen pour cette question."
    extraits = "\n\n".join(
        f"[{i}] {(h.get('payload') or {}).get('title')} ({(h.get('payload') or {}).get('url')})\n"
        f"{(h.get('payload') or {}).get('text')}" for i, h in enumerate(hits, 1))
    try:
        return await llm.chat(_SYS, f"Extraits :\n{extraits}\n\nQuestion : {question}",
                              max_tokens=500, wait_s=0)
    except llm.GpuWarming:
        return "Le GPU souverain démarre (1 à 3 min). Réessayez la question dans une minute."


_DISPATCH = {
    "catalogue_search": _t_catalogue_search,
    "rag_search": _t_rag_search,
    "dataset_get": _t_dataset_get,
    "answer": _t_answer,
}


async def _call(name, args):
    fn = _DISPATCH.get(name)
    if not fn:
        raise ValueError(f"outil inconnu : {name}")
    return await fn(**(args or {}))


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


async def dispatch(msg):
    """Traite un message JSON-RPC. Renvoie l'objet réponse, ou None pour une notification."""
    if not isinstance(msg, dict):
        return _err(None, -32600, "requête invalide")
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}
    if method == "initialize":
        return _ok(mid, {"protocolVersion": PROTOCOL,
                         "capabilities": {"tools": {"listChanged": False}},
                         "serverInfo": SERVER})
    if method and method.startswith("notifications/"):
        return None  # notification : pas de réponse
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": TOOLS})
    if method == "tools/call":
        try:
            text = await _call(params.get("name"), params.get("arguments"))
            return _ok(mid, {"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as e:
            log.warning("mcp tools/call échec : %s", e)
            return _ok(mid, {"content": [{"type": "text", "text": f"Erreur : {e}"}], "isError": True})
    return _err(mid, -32601, f"méthode inconnue : {method}")
