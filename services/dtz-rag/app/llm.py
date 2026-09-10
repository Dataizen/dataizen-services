# -*- coding: utf-8 -*-
"""Accès au LLM souverain via litellm (OpenAI-compatible) : embeddings bge-m3
(CPU, instantané) et chat qwen3.5-35b (GPU, cold-start possible).

Piège qwen3.5 (modèle à raisonnement) : en OpenAI-compat non-stream, il peut
consommer tout le budget en raisonnement et renvoyer un content vide. On passe
`reasoning_effort:"none"` pour l'en dissuader (cf. AI_STACK_INTEGRATION.md)."""
import asyncio
import logging
import time

import httpx

from . import config

log = logging.getLogger("dtz-rag.llm")


def _headers():
    h = {"Content-Type": "application/json"}
    if config.LITELLM_KEY:
        h["Authorization"] = f"Bearer {config.LITELLM_KEY}"
    return h


EMBED_BATCH = 16  # litellm/bge-m3 rejette les gros lots (413) : on découpe.


async def embed(texts):
    """Embeddings d'une liste de textes -> liste de vecteurs 1024-dim.
    Découpé en lots pour rester sous la limite de taille de requête de litellm."""
    if not texts:
        return []
    out = []
    async with httpx.AsyncClient(timeout=120) as cli:
        for i in range(0, len(texts), EMBED_BATCH):
            batch = texts[i:i + EMBED_BATCH]
            r = await cli.post(f"{config.LITELLM_URL}/v1/embeddings", headers=_headers(),
                               json={"model": config.EMBED_MODEL, "input": batch})
            r.raise_for_status()
            data = r.json().get("data", [])
            data.sort(key=lambda d: d.get("index", 0))
            out.extend(d["embedding"] for d in data)
    return out


async def embed_one(text):
    v = await embed([text])
    return v[0] if v else None


class GpuWarming(Exception):
    """Le GPU démarre (cold-start OVH) : réessayer plus tard."""


async def chat(system, user, max_tokens=700, temperature=0.1, wait_s=0):
    """Réponse de chat via l'endpoint ollama natif (proxy gpu-controller).

    `wait_s` : budget d'attente du réveil GPU. Le proxy gpu-controller renvoie par
    intermittence `gpu_not_ready` même quand le GPU vient d'être sollicité (le modèle
    se (re)charge à la demande) : une seule tentative échoue donc souvent à tort. Avec
    wait_s>0, on RÉESSAIE jusqu'à ce que le modèle réponde (cold-start OVH 1 à 3 min),
    et on ne lève GpuWarming qu'au-delà du budget. wait_s=0 (défaut) = une tentative,
    comportement rapide voulu pour l'assistant interactif (message d'attente immédiat)."""
    start = time.monotonic()
    while True:
        try:
            return await _chat_once(system, user, max_tokens, temperature)
        except GpuWarming:
            if time.monotonic() - start >= wait_s:
                raise
            await asyncio.sleep(6)


async def chat_messages(messages, max_tokens=700, temperature=0.1, wait_s=0):
    """Comme chat() mais avec une liste de messages OpenAI complète. Sert au shim
    OpenAI-compatible (/v1/chat/completions) exposé à Directus : think=false (contenu
    non vide), reprise bornée sur réveil GPU."""
    start = time.monotonic()
    while True:
        try:
            return await _chat_once_raw(messages, max_tokens, temperature)
        except GpuWarming:
            if time.monotonic() - start >= wait_s:
                raise
            await asyncio.sleep(6)


async def _chat_once(system, user, max_tokens=700, temperature=0.1):
    return await _chat_once_raw(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens, temperature)


async def _chat_once_raw(messages, max_tokens=700, temperature=0.1):
    """Une tentative d'appel chat (think=false pour un `content` non vide ; lève
    GpuWarming si le GPU n'est pas prêt)."""
    body = {
        "model": config.CHAT_MODEL, "stream": False, "think": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
        "messages": messages,
    }
    try:
        async with httpx.AsyncClient(timeout=120) as cli:
            r = await cli.post(f"{config.OLLAMA_URL}/api/chat",
                               headers={"Content-Type": "application/json"}, json=body)
    except httpx.RequestError as e:
        raise GpuWarming(str(e))
    if r.status_code in (502, 503):
        raise GpuWarming(r.text[:200])
    r.raise_for_status()
    content = ((r.json().get("message") or {}).get("content") or "").strip()
    if not content:
        raise GpuWarming("réponse vide (GPU en démarrage)")
    return content
