# dataizen-services

Micro-services et outils de la plateforme **Dataizen**, hors CKAN et hors portail.
Chacun est une œuvre originale Dataizen (licence MIT), déployé en image versionnée.

## Contenu

- **`services/dtz-rag`** : service RAG (FastAPI). Indexe le catalogue CKAN et le contenu
  éditorial, répond en langage naturel avec sources. Réutilise une stack IA souveraine
  (embeddings, LLM, base vectorielle) via des API HTTP internes.
- **`services/tusd-hook`** : hook du dépôt de gros fichiers (FastAPI). Valide un ticket
  signé, enregistre le fichier déposé (protocole tus) comme ressource CKAN, déclenche le
  chargement datastore.
- **`tools/harmonizer`** : outillage d'harmonisation de données (profil DOLFIN).
- **`tools/terrain`** : génération de tuiles de relief (PMTiles) à partir de MNT.
- **`mdm`** : référentiels territoriaux (chaîne de préparation).

## Licence

MIT (voir [LICENSE](LICENSE)). Composants indépendants de CKAN (dialogue par API HTTP),
donc libres de la licence de notre choix.
