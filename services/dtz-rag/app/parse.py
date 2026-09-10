# -*- coding: utf-8 -*-
"""Découpage en chunks, nettoyage HTML léger, et extraction de documents non
tabulaires (PDF/docx) via docling-serve (réutilisé depuis la stack askem-ai)."""
import hashlib
import re

import httpx

from . import config


def content_hash(text):
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def strip_html(html):
    if not html:
        return ""
    txt = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    txt = re.sub(r"(?s)<[^>]+>", " ", txt)
    txt = (txt.replace("&nbsp;", " ").replace("&amp;", "&")
              .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
              .replace("&quot;", '"'))
    return re.sub(r"\s+", " ", txt).strip()


def chunk(text, size=None, overlap=None):
    """Découpe un texte en tranches de `size` caractères avec recouvrement.
    Coupe de préférence sur une frontière de phrase/espace proche."""
    size = size or config.CHUNK_SIZE
    overlap = overlap or config.CHUNK_OVERLAP
    text = (text or "").strip()
    if len(text) <= size:
        return [text] if text else []
    chunks = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + size, n)
        if end < n:
            window = text[end - 80:end]
            m = max(window.rfind(". "), window.rfind("\n"), window.rfind("; "))
            if m > 0:
                end = end - 80 + m + 1
        chunks.append(text[i:end].strip())
        if end >= n:
            break
        i = max(end - overlap, i + 1)
    return [c for c in chunks if c]


async def docling_extract(file_bytes, filename):
    """Extrait le texte (markdown) d'un document binaire via docling-serve.
    Renvoie '' si docling est indisponible ou échoue (best-effort)."""
    if not config.DOCLING_URL:
        return ""  # parsing de documents désactivé (docling non configuré)
    try:
        files = {"files": (filename, file_bytes)}
        data = {"to_formats": "md", "do_ocr": "false"}
        async with httpx.AsyncClient(timeout=180) as cli:
            r = await cli.post(f"{config.DOCLING_URL}/v1/convert/file",
                               files=files, data=data)
            r.raise_for_status()
            body = r.json()
        # docling-serve renvoie {document:{md_content|text_content}} ou une liste
        doc = body.get("document") or {}
        return (doc.get("md_content") or doc.get("text_content") or "").strip()
    except Exception:
        return ""
