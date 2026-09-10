# -*- coding: utf-8 -*-
"""Index inverse « jeu de données -> instances où il est utilisé ».

Le catalogue CKAN est mutualisé, mais les usages (graphiques, cartes, tableaux de bord)
vivent dans le Directus de CHAQUE instance et référencent une ressource par son rid CKAN.
On balaye donc chaque Directus à la recherche de références aux rid du jeu. Public only :
on ne retient que les usages publiés (la fiche est publique)."""
import logging
import re

import httpx

from . import config, ckan_index

log = logging.getLogger("dtz-rag.usages")

# Directives d'intégration dans le texte des pages/blocs (en plus des blocs m2o dédiés).
_DIR_CARTE = re.compile(r"\[\[carte:(\d+)")
_DIR_GRAPH = re.compile(r"\[\[graphique:(\d+)")


async def _dq(base, collection, fields):
    """Lit tous les items d'une collection Directus avec le jeton de service, SANS filtre
    status (carte_couches / tb_niveaux n'ont pas de champ status : un filtre status y
    provoquerait un 403 sur toute la requête)."""
    headers = {"Authorization": f"Bearer {config.DIRECTUS_TOKEN}"} if config.DIRECTUS_TOKEN else {}
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.get(f"{base}/items/{collection}",
                              params={"fields": fields, "limit": "-1"}, headers=headers)
            r.raise_for_status()
            return r.json().get("data") or []
    except Exception as e:
        log.warning("usages: %s/%s indisponible : %s", base, collection, e)
        return []


async def _dataset_rids(name):
    """Ensemble des rid de ressources du jeu, plus son titre et son organisation."""
    try:
        pkg = await ckan_index._ckan("package_show", {"id": name})
    except Exception:
        return None, {}
    rids = {r.get("id") for r in pkg.get("resources", []) if r.get("id")}
    return rids, {"title": pkg.get("title") or name,
                  "org": (pkg.get("organization") or {}).get("name") or ""}


async def _vehicles_using(base, rids):
    """Cartes / graphiques / tableaux de bord PUBLIÉS de l'instance qui s'appuient sur le
    jeu (par rid). Renvoie {'carte': {id: titre}, 'graphique': {...}, 'tableau-bord': {...}}."""
    veh = {"carte": {}, "graphique": {}, "tableau-bord": {}}
    for g in await _dq(base, "graphiques", "id,titre,dataset,status"):
        if g.get("dataset") in rids and g.get("status") == "published":
            veh["graphique"][g.get("id")] = g.get("titre") or f"Graphique {g.get('id')}"
    couches = await _dq(base, "carte_couches", "carte,dataset,geojson_rid")
    carte_ids = {c.get("carte") for c in couches
                 if c.get("carte") and (c.get("dataset") in rids or c.get("geojson_rid") in rids)}
    if carte_ids:
        cartes = {c.get("id"): c for c in await _dq(base, "cartes", "id,titre,status")}
        for cid in carte_ids:
            c = cartes.get(cid) or {}
            if c.get("status") == "published":
                veh["carte"][cid] = c.get("titre") or f"Carte {cid}"
    niveaux = await _dq(base, "tb_niveaux", "tableau,dataset,contour")
    tb_ids = {n.get("tableau") for n in niveaux
              if n.get("tableau") and (n.get("dataset") in rids or n.get("contour") in rids)}
    if tb_ids:
        tbs = {t.get("id"): t for t in await _dq(base, "tableaux_bord", "id,titre,status")}
        for tid in tb_ids:
            t = tbs.get(tid) or {}
            if t.get("status") == "published":
                veh["tableau-bord"][tid] = t.get("titre") or f"Tableau de bord {tid}"
    return veh


async def _pages_embedding(base, veh):
    """Pour chaque véhicule (carte/graphique/tableau) donné, la ou les pages PUBLIÉES qui
    l'intègrent : via un bloc dédié (page_blocs.carte/graphique/tableau_bord) ou une
    directive [[carte:id]]/[[graphique:id]] dans le texte. Renvoie
    {'carte': {id: [page,...]}, ...} avec page = {slug, title}."""
    idx = {"carte": {}, "graphique": {}, "tableau-bord": {}}
    want = {k: set(v.keys()) for k, v in veh.items()}
    if not any(want.values()):
        return idx
    pages = await _dq(base, "pages", "id,slug,title,status,content")
    pub = {p.get("id"): {"slug": p.get("slug"), "title": p.get("title") or p.get("slug")}
           for p in pages if p.get("status") == "published"}
    blocs = await _dq(base, "page_blocs", "page,type,carte,graphique,tableau_bord,texte,status")

    def add(kind, vid, pid):
        if pid in pub and vid in want[kind]:
            idx[kind].setdefault(vid, [])
            if pub[pid] not in idx[kind][vid]:
                idx[kind][vid].append(pub[pid])

    for b in blocs:
        if b.get("status") not in (None, "published"):
            continue
        pid = b.get("page")
        if b.get("carte"):
            add("carte", b["carte"], pid)
        if b.get("graphique"):
            add("graphique", b["graphique"], pid)
        if b.get("tableau_bord"):
            add("tableau-bord", b["tableau_bord"], pid)
        txt = b.get("texte") or ""
        for cid in _DIR_CARTE.findall(txt):
            add("carte", int(cid), pid)
        for gid in _DIR_GRAPH.findall(txt):
            add("graphique", int(gid), pid)
    for pid, p in pub.items():
        content = (next((x for x in pages if x.get("id") == pid), {}) or {}).get("content") or ""
        for cid in _DIR_CARTE.findall(content):
            add("carte", int(cid), pid)
        for gid in _DIR_GRAPH.findall(content):
            add("graphique", int(gid), pid)
    return idx


async def _instance_usages(base, rids):
    """Usages du jeu dans une instance, orientés PAGE : la ou les pages publiées où il
    apparaît (avec le véhicule : carte/graphique/tableau), plus les véhicules qui
    l'utilisent mais ne sont pas encore posés sur une page publiée (« orphelins »)."""
    veh = await _vehicles_using(base, rids)
    idx = await _pages_embedding(base, veh)
    pages = {}   # slug -> {slug, title, via:[{type,titre}]}
    orphelins = []
    for kind, items in veh.items():
        for vid, titre in items.items():
            hosts = idx[kind].get(vid) or []
            if not hosts:
                orphelins.append({"type": kind, "titre": titre})
                continue
            for p in hosts:
                e = pages.setdefault(p["slug"], {"slug": p["slug"], "title": p["title"], "via": []})
                e["via"].append({"type": kind, "titre": titre})
    return {"pages": sorted(pages.values(), key=lambda x: x["title"].lower()),
            "orphelins": orphelins}


async def _ckan_post(action, payload):
    """Appel CKAN en écriture (token sysadmin), ex. package_patch."""
    headers = {"Authorization": config.CKAN_TOKEN, "Content-Type": "application/json"} \
        if config.CKAN_TOKEN else {}
    async with httpx.AsyncClient(timeout=60) as cli:
        r = await cli.post(f"{config.CKAN_URL}/api/3/action/{action}", json=payload, headers=headers)
        r.raise_for_status()
        return r.json().get("result")


async def _instance_exposed_rids(base):
    """rids de ressources EXPOSÉS sur au moins une page publiée de cette instance
    (via un bloc carte/graphique/tableau ou une directive). Une passe par instance."""
    g_ds = {g["id"]: g.get("dataset") for g in await _dq(base, "graphiques", "id,dataset,status")
            if g.get("status") == "published" and g.get("dataset")}
    carte_rids = {}
    for c in await _dq(base, "carte_couches", "carte,dataset,geojson_rid"):
        cid = c.get("carte")
        if not cid:
            continue
        for r in (c.get("dataset"), c.get("geojson_rid")):
            if r:
                carte_rids.setdefault(cid, set()).add(r)
    cartes_pub = {c["id"] for c in await _dq(base, "cartes", "id,status") if c.get("status") == "published"}
    tb_rids = {}
    for n in await _dq(base, "tb_niveaux", "tableau,dataset,contour"):
        tid = n.get("tableau")
        if not tid:
            continue
        for r in (n.get("dataset"), n.get("contour")):
            if r:
                tb_rids.setdefault(tid, set()).add(r)
    tb_pub = {t["id"] for t in await _dq(base, "tableaux_bord", "id,status") if t.get("status") == "published"}
    pages = await _dq(base, "pages", "id,status,content")
    pub_ids = {p["id"] for p in pages if p.get("status") == "published"}
    blocs = await _dq(base, "page_blocs", "page,carte,graphique,tableau_bord,texte,status")
    exposed = set()

    def ex_carte(cid):
        if cid in cartes_pub:
            exposed.update(carte_rids.get(cid, ()))

    def ex_graph(gid):
        if g_ds.get(gid):
            exposed.add(g_ds[gid])

    def ex_tb(tid):
        if tid in tb_pub:
            exposed.update(tb_rids.get(tid, ()))

    for b in blocs:
        if b.get("status") not in (None, "published") or b.get("page") not in pub_ids:
            continue
        if b.get("carte"):
            ex_carte(b["carte"])
        if b.get("graphique"):
            ex_graph(b["graphique"])
        if b.get("tableau_bord"):
            ex_tb(b["tableau_bord"])
        txt = b.get("texte") or ""
        for cid in _DIR_CARTE.findall(txt):
            ex_carte(int(cid))
        for gid in _DIR_GRAPH.findall(txt):
            ex_graph(int(gid))
    for p in pages:
        if p["id"] not in pub_ids:
            continue
        txt = p.get("content") or ""
        for cid in _DIR_CARTE.findall(txt):
            ex_carte(int(cid))
        for gid in _DIR_GRAPH.findall(txt):
            ex_graph(int(gid))
    return exposed


async def build_global_index():
    """rid de ressource -> set(instances où il est exposé sur une page publiée)."""
    idx = {}
    for instance, base in config.directus_instances():
        for rid in await _instance_exposed_rids(base):
            idx.setdefault(rid, set()).add(instance)
    return idx


async def _stamp_dataset(pkg, instances):
    """Écrit/retire les extras usages_instances / usages_count sur un jeu, en préservant
    les autres extras. Ne patche que si la valeur change (évite le bruit et les réindex
    inutiles). instances = liste triée des instances où le jeu est exposé."""
    csv = ",".join(instances)
    cur = {e["key"]: e.get("value") for e in (pkg.get("extras") or [])}
    if cur.get("usages_instances", "") == csv and str(cur.get("usages_count", "")) == str(len(instances)):
        return False
    extras = [e for e in (pkg.get("extras") or []) if e.get("key") not in ("usages_instances", "usages_count")]
    if instances:  # non utilisé -> on laisse les clés ABSENTES (filtre "non utilisé" = absence)
        extras.append({"key": "usages_instances", "value": csv})
        extras.append({"key": "usages_count", "value": str(len(instances))})
    await _ckan_post("package_patch", {"id": pkg["id"], "extras": extras})
    return True


async def stamp_all():
    """Recalcule l'usage de tous les jeux publics et met à jour leurs extras. Balaye
    chaque Directus une seule fois (index global), puis parcourt le catalogue."""
    idx = await build_global_index()
    patched = total = 0
    start = 0
    while True:
        res = await ckan_index._ckan("package_search",
                                     {"q": "*:*", "fq": "+capacity:public", "rows": 100, "start": start})
        results = res.get("results", [])
        if not results:
            break
        for pkg in results:
            total += 1
            rids = {r.get("id") for r in pkg.get("resources", []) if r.get("id")}
            insts = sorted(set().union(*[idx.get(r, set()) for r in rids])) if rids else []
            try:
                if await _stamp_dataset(pkg, insts):
                    patched += 1
            except Exception as e:
                log.warning("stamp %s échec : %s", pkg.get("name"), e)
        start += 100
        if start >= res.get("count", 0):
            break
    log.info("usages stampés : %d jeux mis à jour sur %d", patched, total)
    return {"total": total, "patched": patched, "rids_exposes": len(idx)}


async def usages_for_dataset(name):
    """Renvoie {dataset, title, org, instances:[{instance, portal, pages:[...], orphelins:[...]}]}."""
    rids, info = await _dataset_rids(name)
    if rids is None:
        return {"dataset": name, "error": "jeu introuvable", "instances": []}
    out = []
    for instance, base in config.directus_instances():
        u = await _instance_usages(base, rids)
        if u["pages"] or u["orphelins"]:
            out.append({"instance": instance,
                        "portal": f"https://{instance}.{config.PUBLIC_DOMAIN}",
                        "pages": u["pages"], "orphelins": u["orphelins"]})
    return {"dataset": name, "title": info.get("title"), "org": info.get("org"),
            "instances": out}
