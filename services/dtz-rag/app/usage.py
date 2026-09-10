# -*- coding: utf-8 -*-
"""Suivi d'usage du GPU souverain : sessions d'allumage (polling de l'état) et
événements d'activité (ce qui sollicite le GPU via dtz-rag). Stocké dans Postgres
(table lue par la forge admin). Tolérant : si la DB est indisponible, on n'échoue
jamais l'appel métier, on journalise seulement."""
import asyncio
import contextlib
import logging

import asyncpg
import httpx

from . import config

log = logging.getLogger("dtz-rag.usage")

_pool = None
_current_session = None  # id de la session d'allumage en cours (mémoire)


def _gpu_base():
    url = config.OLLAMA_URL or ""
    return url.split("/gpu/proxy")[0] if "/gpu/proxy" in url else url.rstrip("/")


async def init():
    """Crée le pool et les tables. Non bloquant : en cas d'échec, le suivi est
    simplement désactivé (record_event devient un no-op)."""
    global _pool, _current_session
    if not config.PG_DSN:
        log.info("usage: pas de DSN Postgres, suivi GPU désactivé")
        return
    try:
        _pool = await asyncpg.create_pool(config.PG_DSN, min_size=1, max_size=3, timeout=10)
        async with _pool.acquire() as c:
            await c.execute("""
                CREATE TABLE IF NOT EXISTS gpu_sessions (
                    id serial PRIMARY KEY,
                    started_at timestamptz NOT NULL,
                    last_seen  timestamptz NOT NULL,
                    ended_at   timestamptz,
                    peak_billing_minutes real
                );
                CREATE TABLE IF NOT EXISTS gpu_events (
                    id serial PRIMARY KEY,
                    at timestamptz NOT NULL DEFAULT now(),
                    instance text,
                    source   text NOT NULL,
                    detail   text,
                    user_email text
                );
                CREATE INDEX IF NOT EXISTS gpu_events_at_idx ON gpu_events (at DESC);
                CREATE TABLE IF NOT EXISTS parc_events (
                    id serial PRIMARY KEY,
                    at timestamptz NOT NULL DEFAULT now(),
                    instance text,
                    type   text NOT NULL,
                    detail text
                );
                CREATE INDEX IF NOT EXISTS parc_events_inst_idx ON parc_events (instance, at DESC);
                CREATE INDEX IF NOT EXISTS parc_events_at_idx ON parc_events (at DESC);
            """)
            # reprise : adopter une éventuelle session encore ouverte
            row = await c.fetchrow(
                "SELECT id FROM gpu_sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1")
            _current_session = row["id"] if row else None
        log.info("usage: suivi GPU actif (session ouverte reprise=%s)", _current_session)
    except Exception as e:
        _pool = None
        log.warning("usage: init Postgres échouée, suivi GPU désactivé (%s)", e)


async def record_event(source, instance=None, detail=None, user_email=None):
    """Journalise une sollicitation du GPU (assistant, génération, réveil manuel…)."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as c:
            await c.execute(
                "INSERT INTO gpu_events (instance, source, detail, user_email) "
                "VALUES ($1,$2,$3,$4)",
                instance, source, (detail or "")[:300], user_email)
    except Exception as e:
        log.debug("usage: record_event échec (%s)", e)


async def record_parc_event(type, instance=None, detail=None):
    """Journalise un événement de cycle de vie du parc (provisioning, suppression,
    création de compte, envoi d'email). Alimente la timeline de la page instance."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as c:
            await c.execute(
                "INSERT INTO parc_events (instance, type, detail) VALUES ($1,$2,$3)",
                instance, (type or "")[:60], (detail or "")[:500])
    except Exception as e:
        log.debug("usage: record_parc_event échec (%s)", e)


async def _fetch_status():
    base = _gpu_base()
    if not base:
        return None
    async with httpx.AsyncClient(timeout=8) as c:
        return (await c.get(f"{base}/gpu/status")).json()


async def poll_loop():
    """Échantillonne l'état du GPU toutes les 60 s et tient à jour les sessions
    d'allumage (début / durée / minutes facturées de pointe). Couvre TOUS les
    consommateurs (c'est le contrôleur qui fait foi)."""
    global _current_session
    if not _pool:
        return
    while True:
        try:
            s = await _fetch_status()
            ready = bool(s and s.get("ollama_ready") and s.get("model_loaded")
                         and s.get("ollama_responding"))
            bill = (s or {}).get("billing_remaining_minutes")
            async with _pool.acquire() as c:
                if ready and _current_session is None:
                    row = await c.fetchrow(
                        "INSERT INTO gpu_sessions (started_at, last_seen, peak_billing_minutes) "
                        "VALUES (now(), now(), $1) RETURNING id", bill)
                    _current_session = row["id"]
                    log.info("usage: session GPU %s ouverte", _current_session)
                elif ready and _current_session is not None:
                    await c.execute(
                        "UPDATE gpu_sessions SET last_seen=now(), "
                        "peak_billing_minutes=GREATEST(COALESCE(peak_billing_minutes,0),COALESCE($2,0)) "
                        "WHERE id=$1", _current_session, bill)
                elif not ready and _current_session is not None:
                    await c.execute(
                        "UPDATE gpu_sessions SET ended_at=now() WHERE id=$1", _current_session)
                    log.info("usage: session GPU %s fermée", _current_session)
                    _current_session = None
        except Exception as e:
            log.debug("usage: poll échec (%s)", e)
        await asyncio.sleep(60)


async def close():
    if _pool:
        with contextlib.suppress(Exception):
            await _pool.close()
