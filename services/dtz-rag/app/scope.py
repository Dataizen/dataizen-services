# -*- coding: utf-8 -*-
"""Traduction d'un périmètre de requête en filtre qdrant (v1 : public seulement).

scope = {"instance": "<nom>"|None, "orgs": ["orgA", ...]|None}
- orgs = None  -> tous les jeux CKAN publics (open-webui global)
- orgs = [...] -> jeux CKAN de ces organisations (résolu par le portail via catalogueOrgs)
- instance     -> contenu CMS de cette instance ; None -> tout le CMS public
"""

_PUBLIC = {"key": "visibility", "match": {"value": "public"}}


def build(scope):
    """Renvoie (must, should) pour store.search."""
    scope = scope or {}
    instance = scope.get("instance")
    orgs = scope.get("orgs")

    if not instance and (orgs is None):
        # périmètre global : tout le public (CKAN + CMS)
        return [_PUBLIC], None

    ckan = {"must": [_PUBLIC, {"key": "source", "match": {"value": "ckan"}}]}
    if orgs:
        ckan["must"].append({"key": "org", "match": {"any": list(orgs)}})
    cms = {"must": [_PUBLIC, {"key": "source", "match": {"value": "cms"}}]}
    if instance:
        cms["must"].append({"key": "instance", "match": {"value": instance}})

    # au moins une des deux branches (CKAN de mes orgs OU CMS de mon instance)
    return [_PUBLIC], [ckan, cms]
