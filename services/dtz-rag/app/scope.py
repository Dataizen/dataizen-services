# -*- coding: utf-8 -*-
"""Traduction d'un périmètre de requête en filtre qdrant (v1 : public seulement).

scope = {"instance": "<nom>"|None, "orgs": ["orgA", ...]|None}
- orgs = None  -> tous les jeux CKAN publics (open-webui global)
- orgs = [...] -> jeux CKAN de ces organisations (résolu par le portail via catalogueOrgs)
- instance     -> contenu CMS de cette instance ; None -> tout le CMS public
"""

_PUBLIC = {"key": "visibility", "match": {"value": "public"}}


def build(scope):
    """Renvoie (must, should) pour store.search.

    orgs = None  -> toutes les orgs CKAN publiques (périmètre global voulu)
    orgs = []    -> sélection vide : AUCUN jeu CKAN (la branche CKAN n'est pas ajoutée),
                    distinct de None pour ne pas exposer tout le catalogue par défaut
    orgs = [...] -> uniquement ces orgs
    """
    scope = scope or {}
    instance = scope.get("instance")
    orgs = scope.get("orgs")

    if not instance and orgs is None:
        # périmètre global : tout le public (CKAN + CMS)
        return [_PUBLIC], None

    should = []
    # Branche CKAN : ajoutée seulement si orgs n'est PAS une sélection vide.
    if orgs is None or orgs:
        ckan = {"must": [_PUBLIC, {"key": "source", "match": {"value": "ckan"}}]}
        if orgs:
            ckan["must"].append({"key": "org", "match": {"any": list(orgs)}})
        should.append(ckan)
    # Branche CMS : contenu éditorial de l'instance (ou tout le CMS public sans instance).
    cms = {"must": [_PUBLIC, {"key": "source", "match": {"value": "cms"}}]}
    if instance:
        cms["must"].append({"key": "instance", "match": {"value": instance}})
    should.append(cms)

    # au moins une des branches retenues (CKAN de mes orgs et/ou CMS de mon instance)
    return [_PUBLIC], should
