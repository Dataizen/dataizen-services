# -*- coding: utf-8 -*-
"""Configuration du service dtz-rag, lue depuis l'environnement (--env-file
/data/svc/dtz-rag.env posé par Ansible). Aucune valeur secrète en dur."""
import os


def _clean(url: str) -> str:
    return (url or "").rstrip("/")


# LLM souverain (litellm, passerelle OpenAI-compatible, sur le vRack)
LITELLM_URL = _clean(os.getenv("LITELLM_URL", "http://10.2.2.1:4000"))
LITELLM_KEY = os.getenv("LITELLM_KEY", "")
EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "text-embedding")  # bge-m3, 1024 dim
EMBED_DIM = int(os.getenv("RAG_EMBED_DIM", "1024"))

# Chat : endpoint ollama natif (proxy gpu-controller) avec think=false, seul moyen
# fiable d'éviter le content vide de qwen3.5 (modèle à raisonnement). Cf. la forge.
OLLAMA_URL = _clean(os.getenv("OLLAMA_URL", "http://10.2.2.1:8111/gpu/proxy"))
CHAT_MODEL = os.getenv("RAG_CHAT_MODEL", "qwen3.5:35b")

# Base vectorielle (qdrant dédiée à Dataizen, sur dtz-core, réseau dtz)
QDRANT_URL = _clean(os.getenv("QDRANT_URL", "http://qdrant:6333"))
QDRANT_COLLECTION = os.getenv("RAG_COLLECTION", "dataizen_docs")

# Extraction de documents (docling). Vide = parsing de documents désactivé
# (v1 sur dtz-core : docling pas encore déployé localement).
DOCLING_URL = _clean(os.getenv("DOCLING_URL", ""))

# CKAN (accès interne, token de service sysadmin)
CKAN_URL = _clean(os.getenv("CKAN_URL", "http://ckan:5000"))
CKAN_TOKEN = os.getenv("CKAN_TOKEN", "")

# CMS Directus : liste des instances "nom=url" séparées par des virgules,
# ex. "ici2050=http://directus-ici2050:8055,demo=http://directus-demo:8055".
# Lecture publique (pas de token requis pour le contenu publié).
DIRECTUS_INSTANCES = os.getenv("DIRECTUS_INSTANCES", "")
# Token de service Directus (écriture : génération d'éléments IA type graphique).
DIRECTUS_TOKEN = os.getenv("DIRECTUS_TOKEN", "")

# Postgres (suivi d'usage du GPU : sessions d'allumage + événements d'activité).
# DSN complet, ex. postgresql://dataizen:<pw>@postgres:5432/dataizen. Vide = suivi off.
PG_DSN = os.getenv("PG_DSN", "")

# Domaine public (pour construire les liens de sources vers les fiches/pages)
PUBLIC_DOMAIN = os.getenv("PUBLIC_DOMAIN", "core.dataizen.eu")
CKAN_PUBLIC_URL = _clean(os.getenv("CKAN_PUBLIC_URL", f"https://data.{PUBLIC_DOMAIN}"))

# Jeton partagé pour les webhooks de fraîcheur (CKAN / Directus -> dtz-rag)
WEBHOOK_TOKEN = os.getenv("RAG_WEBHOOK_TOKEN", "")

# SMTP (notifications : dépôt à valider, jeu validé). Relais mutualisé (askem.eu).
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
SMTP_FROM_DISPLAY = os.getenv("SMTP_FROM_DISPLAY", "Dataizen")
SMTP_ENVELOPE_FROM = os.getenv("SMTP_ENVELOPE_FROM", "") or SMTP_FROM
SMTP_REPLY_TO = os.getenv("SMTP_REPLY_TO", "")
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "true").lower() in ("1", "true", "yes")

# Découpage
CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "200"))
# Échantillon de lignes pour la proposition IA (mapping, graphiques…) : petit.
MAX_ROWS = int(os.getenv("RAG_MAX_ROWS", "20"))
# Indexation RAG du CONTENU tabulaire : nombre max de lignes indexées par ressource
# (au-delà, troncature signalée dans le doc et les logs). 0 = ne pas indexer les lignes.
INDEX_MAX_ROWS = int(os.getenv("RAG_INDEX_MAX_ROWS", "5000"))
# Colonnes ignorées à l'indexation des lignes (géométries volumineuses, sans valeur RAG)
SKIP_ROW_COLS = {"geometry", "the_geom", "_geom", "geom", "wkb_geometry"}


def directus_instances():
    """Renvoie [(nom, url), ...] à partir de DIRECTUS_INSTANCES."""
    out = []
    for part in DIRECTUS_INSTANCES.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, url = part.split("=", 1)
        out.append((name.strip(), _clean(url.strip())))
    return out
