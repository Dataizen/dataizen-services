#!/usr/bin/env python3
"""Tests unitaires + validation de format/schéma des writers du pivot-harmonizer.

Zéro dépendance (stdlib `unittest` uniquement, comme le reste du toolkit).
Exécution : `python3 -m unittest discover -s tests` depuis la racine du dépôt.

Couvre :
- l'adaptateur générique `harmonize_generic.harmonize` (structure NGSI-LD) ;
- les writers `to_harmonized_csv` (CSV harmonisé) et `to_geojson` (FeatureCollection) ;
- la VALIDATION du format/schéma produit (NGSI-LD, GeoJSON, CSV) ;
- l'enrichissement par référentiels (GBIF/Wikidata) en mode hors-ligne (cache pré-rempli) ;
- la compilation d'un `.dolfin` (`dolfin2model.parse`).
"""
import csv
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harmonize_generic as H  # noqa: E402
import references as R          # noqa: E402
import dolfin2model             # noqa: E402


ROWS = [
    {"gid": "1", "nom": "Gymnase Jean Moulin", "type": "stade",
     "commune": "Dijon", "lon": "5.041", "lat": "47.322"},
    {"gid": "2", "nom": "Médiathèque", "type": "bibliothèque",
     "commune": "Dijon", "lon": "5.05", "lat": "47.31"},
    {"gid": "3", "nom": "Sans coord", "type": "parc",
     "commune": "Dijon", "lon": "", "lat": ""},
]
MAPPING = {
    "type": "PointOfInterest",
    "context": "https://smartdatamodels.org/context.jsonld",
    "id_prefix": "urn:ngsi-ld:PointOfInterest:",
    "id_field": "nom",
    "fields": {"name": "nom", "category": "type", "address": "commune"},
    "location": {"lon": "lon", "lat": "lat"},
}


# --------------------------------------------------------------------------- #
# Validateurs de schéma (best-effort, stdlib)
# --------------------------------------------------------------------------- #
def assert_valid_ngsild(testcase, entities):
    testcase.assertIsInstance(entities, list)
    for e in entities:
        testcase.assertIsInstance(e.get("id"), str, "entité sans id string")
        testcase.assertTrue(e["id"].startswith("urn:ngsi-ld:"), f"id non urn: {e['id']}")
        testcase.assertIsInstance(e.get("type"), str, "entité sans type")
        for k, v in e.items():
            if k in ("id", "type"):
                continue
            testcase.assertIsInstance(v, dict, f"propriété {k} non structurée")
            testcase.assertIn(v.get("type"), ("Property", "GeoProperty", "Relationship"),
                              f"type NGSI-LD invalide pour {k}: {v.get('type')}")
            if v["type"] == "GeoProperty":
                geo = v.get("value") or {}
                testcase.assertEqual(geo.get("type"), "Point")
                coords = geo.get("coordinates")
                testcase.assertIsInstance(coords, list)
                testcase.assertEqual(len(coords), 2)
                testcase.assertTrue(all(isinstance(c, (int, float)) for c in coords))
            else:
                testcase.assertIn("value", v)


def assert_valid_geojson(testcase, fc):
    testcase.assertEqual(fc.get("type"), "FeatureCollection")
    testcase.assertIsInstance(fc.get("features"), list)
    for f in fc["features"]:
        testcase.assertEqual(f.get("type"), "Feature")
        testcase.assertIsInstance(f.get("properties"), dict)
        geom = f.get("geometry")
        if geom is not None:
            testcase.assertEqual(geom.get("type"), "Point")
            coords = geom.get("coordinates")
            testcase.assertIsInstance(coords, list)
            testcase.assertEqual(len(coords), 2)
            testcase.assertTrue(all(isinstance(c, (int, float)) for c in coords))


# --------------------------------------------------------------------------- #
class TestHarmonizeNGSILD(unittest.TestCase):
    def test_entities_structure(self):
        entities, warnings = H.harmonize(ROWS, MAPPING)
        self.assertEqual(len(entities), 3)
        assert_valid_ngsild(self, entities)

    def test_id_and_fields(self):
        entities, _ = H.harmonize(ROWS, MAPPING)
        e0 = entities[0]
        self.assertEqual(e0["id"], "urn:ngsi-ld:PointOfInterest:Gymnase-Jean-Moulin")
        self.assertEqual(e0["name"]["value"], "Gymnase Jean Moulin")
        self.assertEqual(e0["category"]["value"], "stade")

    def test_location_geoproperty_and_missing(self):
        entities, _ = H.harmonize(ROWS, MAPPING)
        self.assertEqual(entities[0]["location"]["value"]["coordinates"], [5.041, 47.322])
        # ligne 3 : pas de coordonnées -> pas de location
        self.assertNotIn("location", entities[2])


class TestWriters(unittest.TestCase):
    def test_geojson_format(self):
        fc = H.to_geojson(ROWS, MAPPING)
        assert_valid_geojson(self, fc)
        self.assertEqual(len(fc["features"]), 3)
        self.assertEqual(fc["features"][0]["geometry"]["coordinates"], [5.041, 47.322])
        self.assertIsNone(fc["features"][2]["geometry"])  # sans coord -> geometry null

    def test_harmonized_csv_format(self):
        text = H.to_harmonized_csv(ROWS, MAPPING)
        rows = list(csv.reader(io.StringIO(text)))
        header = rows[0]
        # colonnes aux noms canoniques du modèle
        self.assertEqual(header[:6], ["id", "name", "category", "address", "longitude", "latitude"])
        self.assertEqual(len(rows), 4)  # header + 3 lignes
        self.assertEqual(rows[1][1], "Gymnase Jean Moulin")


class TestReferencesOffline(unittest.TestCase):
    """Enrichissement sans réseau : on pré-remplit les caches des résolveurs."""
    def setUp(self):
        # Offline strict : toute résolution NON cachée échouerait via le réseau -> on
        # neutralise l'accès réseau (les résolveurs dégradent alors en None).
        self._orig_get_json = R._get_json
        def _no_network(url):
            raise RuntimeError("réseau désactivé (test offline)")
        R._get_json = _no_network
        R._gbif_cache.clear()
        R._wikidata_cache.clear()
        R._wikidata_cache["fr|stade"] = {"url": "https://www.wikidata.org/entity/Q6949",
                                         "id": "Q6949", "label": "Stade"}
        R._wikidata_cache["fr|bibliothèque"] = {"url": "https://www.wikidata.org/entity/Q7075",
                                               "id": "Q7075", "label": "bibliothèque"}
        # 'parc' laissé non résolu -> résolveur réseau neutralisé -> pas d'enrichissement

    def tearDown(self):
        R._get_json = self._orig_get_json

    def test_ngsild_enriched(self):
        entities, _ = H.harmonize(ROWS, MAPPING)  # PointOfInterest -> category:wikidata
        self.assertEqual(entities[0]["categoryRef"]["value"], "https://www.wikidata.org/entity/Q6949")
        self.assertEqual(entities[0]["categoryCanonical"]["value"], "Stade")
        self.assertNotIn("categoryRef", entities[2])  # 'parc' non résolu

    def test_csv_and_geojson_enriched(self):
        H.harmonize(ROWS, MAPPING)  # réchauffe le cache via enrich()
        header = list(csv.reader(io.StringIO(H.to_harmonized_csv(ROWS, MAPPING))))[0]
        self.assertIn("category_ref", header)
        self.assertIn("category_canonical", header)
        props = H.to_geojson(ROWS, MAPPING)["features"][0]["properties"]
        self.assertEqual(props["categoryRef"], "https://www.wikidata.org/entity/Q6949")

    def test_cached_result_no_network(self):
        self.assertEqual(R.cached_result("wikidata", "stade")["id"], "Q6949")
        self.assertIsNone(R.cached_result("wikidata", "inconnu-xyz"))
        self.assertIsNone(R.cached_result("gbif", "Quercus robur"))  # cache vide -> None


class TestDolfinCompile(unittest.TestCase):
    def test_parse_minimal(self):
        src = ('package <http://ex/uc/poi>:\n  dolfin_version "1"\n\n'
               'concept PointOfInterest:\n  has name: one string\n  has category: optional string\n')
        concepts = dolfin2model.parse(src)
        self.assertTrue(any(getattr(c, "name", None) == "PointOfInterest" for c in concepts))


if __name__ == "__main__":
    unittest.main()
