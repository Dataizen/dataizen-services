# -*- coding: utf-8 -*-
"""Hook HTTP de tusd : enregistre un fichier déposé (upload résumable) comme
ressource CKAN, sans le faire transiter par le web tier.

Flux : le portail (server-side, authentifié Keycloak) émet un TICKET signé (HMAC)
autorisant un dépôt sur un jeu précis. Le navigateur envoie le fichier à tusd avec
ce ticket en métadonnée. tusd appelle ce hook :
  - pre-create  : on valide le ticket (sinon on REFUSE l'upload tout de suite) ;
  - post-finish : on crée/complète la ressource CKAN, on place le fichier dans le
                  filestore (mv instantané, même volume ZFS) et on marque url_type=upload
                  (le plugin dataload_router charge alors le datastore automatiquement).

Aucune donnée ne transite deux fois : le fichier est écrit une fois par tusd, puis
déplacé (rename) dans le filestore CKAN.
"""
import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import threading
import time

import httpx
from fastapi import FastAPI, Request, Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tusd-hook")

CKAN_URL = os.getenv("CKAN_URL", "http://ckan:5000").rstrip("/")
CKAN_TOKEN = os.getenv("CKAN_TOKEN", "")
HMAC_SECRET = os.getenv("DEPOT_HMAC_SECRET", "").encode()
# Racines montées depuis l'hôte. IMPORTANT : le staging tusd DOIT être sur le MÊME
# dataset ZFS que le filestore CKAN (data/svc/ckan est un dataset distinct de data/svc),
# sinon os.replace échoue en cross-device (EXDEV) et il faudrait recopier jusqu'à 10 Go.
# D'où le staging sous ckan/ (et non /data/svc/tusd). Le hook monte /data/svc -> /srv/data.
STAGING_DIR = os.getenv("STAGING_DIR", "/srv/data/ckan/tusd-staging")
CKAN_RESOURCES_DIR = os.getenv("CKAN_RESOURCES_DIR", "/srv/data/ckan/resources")

# Formats que xloader sait charger DIRECTEMENT -> on soumet xloader (le routeur ne se
# déclenche pas seul car on place le fichier à la main, sans "upload" dans la requête).
# NB : PAS de geojson/json/kml ici : xloader ne les lit pas (« Format geojson is not
# supported »). Ceux-là sont convertis en CSV par dataload_router (job asynchrone ogr2ogr),
# et c'est le CSV dérivé qui est chargé. On les laisse donc au routeur.
TABULAR_FORMATS = {"CSV", "TSV", "XLS", "XLSX", "ODS"}

# Délai généreux : un resource_patch peut déclencher un traitement CKAN un peu long.
CKAN_TIMEOUT = float(os.getenv("CKAN_TIMEOUT", "900"))

app = FastAPI()


def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_ticket(ticket):
    """Vérifie le ticket HMAC émis par le portail. Renvoie le payload {pkg, rid?, exp}
    si valide et non expiré, sinon None."""
    try:
        body_b64, sig_b64 = ticket.split(".", 1)
        expected = hmac.new(HMAC_SECRET, body_b64.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64d(sig_b64)):
            return None
        payload = json.loads(_b64d(body_b64))
        if float(payload.get("exp", 0)) < time.time():
            return None
        return payload
    except Exception:
        return None


def _ckan(action, data):
    r = httpx.post(f"{CKAN_URL}/api/3/action/{action}",
                   headers={"Authorization": CKAN_TOKEN, "Content-Type": "application/json"},
                   json=data, timeout=CKAN_TIMEOUT)
    r.raise_for_status()
    d = r.json()
    if not d.get("success"):
        raise RuntimeError(f"CKAN {action}: {d.get('error')}")
    return d["result"]


def _ckan_owner():
    """uid:gid des fichiers de ressources CKAN existants (pour aligner le propriétaire
    du fichier déplacé, sinon CKAN/loader ne peut pas le lire)."""
    for root, _dirs, files in os.walk(CKAN_RESOURCES_DIR):
        for f in files:
            st = os.stat(os.path.join(root, f))
            return st.st_uid, st.st_gid
    return None


def _fmt_mime(filename):
    ext = os.path.splitext(filename)[1].lstrip(".").upper()
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return (ext or "DATA"), mime


def register(upload_id, filename, meta):
    """post-finish : place le fichier dans le filestore CKAN et crée/complète la ressource."""
    payload = verify_ticket(meta.get("ticket", ""))
    if not payload:
        log.error("ticket invalide/absent pour upload %s : rien fait", upload_id)
        return
    src = os.path.join(STAGING_DIR, upload_id)
    if not os.path.isfile(src):
        log.error("fichier staging introuvable : %s", src)
        return
    size = os.path.getsize(src)
    fmt, mime = _fmt_mime(filename)

    # Ressource cible : remplacement (rid dans le ticket) ou création dans le jeu (pkg).
    rid = payload.get("rid")
    if not rid:
        res = _ckan("resource_create", {
            "package_id": payload["pkg"], "name": filename, "url": filename,
            "format": fmt, "mimetype": mime})
        rid = res["id"]

    dst = os.path.join(CKAN_RESOURCES_DIR, rid[0:3], rid[3:6], rid[6:])
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.replace(src, dst)  # même volume ZFS -> rename instantané
    owner = _ckan_owner()
    if owner:
        os.chown(dst, owner[0], owner[1])
    # nettoyage du sidecar .info de tusd
    try:
        os.remove(os.path.join(STAGING_DIR, upload_id + ".info"))
    except OSError:
        pass

    _ckan("resource_patch", {
        "id": rid, "url_type": "upload", "url": filename, "size": size,
        "format": fmt, "mimetype": mime})
    # Chargement datastore pour les tabulaires (le routeur ne se déclenche pas sans
    # "upload" dans la requête ; on soumet donc explicitement à xloader). SANS plafond de
    # taille : le loader (datapusher-plus) et dataload_router (ogr2ogr pour geojson) sont
    # en streaming, mémoire bornée. Les gros fichiers sont donc bien chargés.
    loaded = ""
    if fmt in TABULAR_FORMATS:
        try:
            _ckan("xloader_submit", {"resource_id": rid})
            loaded = " ; xloader soumis (datastore)"
        except Exception as e:
            log.warning("xloader_submit a échoué pour %s : %s", rid, e)
    log.info("ressource %s enregistrée (%s, %d octets) sur le jeu %s%s",
             rid, filename, size, payload.get("pkg", "?"), loaded)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/hooks")
async def hooks(request: Request):
    body = await request.json()
    htype = body.get("Type", "")
    ev = body.get("Event", {})
    up = ev.get("Upload", {}) or {}
    meta = up.get("MetaData", {}) or {}

    if htype == "pre-create":
        # Refuse l'upload immédiatement si le ticket n'est pas valide (économise le transfert).
        if not verify_ticket(meta.get("ticket", "")):
            return Response(status_code=400, content="ticket de dépôt invalide ou expiré")
        return {"HTTPResponse": {"StatusCode": 200}}

    if htype == "post-finish":
        filename = meta.get("filename") or up.get("ID", "fichier")
        # Enregistrement en ARRIÈRE-PLAN : tusd reçoit 200 immédiatement (non bloquant),
        # le travail CKAN (déplacement + patch + xloader) se fait sans retenir la réponse.
        def _bg():
            try:
                register(up.get("ID", ""), filename, meta)
            except Exception as e:
                log.exception("échec enregistrement CKAN : %s", e)
        threading.Thread(target=_bg, daemon=True).start()
        return {"HTTPResponse": {"StatusCode": 200}}

    return {"HTTPResponse": {"StatusCode": 200}}
