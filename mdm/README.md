# mdm : référentiels de la base centrale

Implémentation v0 du MDM du blueprint (§8) : le schéma `mdm` de la base centrale (base `datastore`) porte les tables de référence partagées par tous les territoires et instances.

## État actuel

| Table | Contenu | Source | Chargement |
|-------|---------|--------|------------|
| `mdm.communes` | Communes de France entière : code INSEE, nom, département, région, EPCI, SIREN, population | Code Officiel Géographique via geo.api.gouv.fr | [`load_communes.sh`](load_communes.sh) (rerunnable, table reconstruite, datée par `valid_from`) |

## Cycle de publication (blueprint §8.4)

Le référentiel est publié comme n'importe quelle donnée :

1. `./load_communes.sh` : charge/actualise `mdm.communes`
2. Le CSV est déposé dans CKAN (organisation `referentiels`, dataset `referentiel-communes-france`) : chaîne normale, datastore, métadonnées
3. `dtz-api create referentiel-communes-france --slug communes` : API OpenAPI sur https://api.core.dataizen.eu/communes

Rafraîchissement : **un clic depuis la forge** (https://admin.core.dataizen.eu/referentiel), qui exécute `dtz-refresh-communes.sh` côté serveur : rechargement atomique de `mdm.communes` + mise à jour de la ressource CKAN. La vue API pointe sur `mdm.communes` (pas la copie datastore), le rafraîchissement est donc transparent pour les consommateurs.

## À venir (voir [BACKLOG.md](../docs/BACKLOG.md))

- Reprise de l'ETL dbt `referentiel_territorial` pour la chaîne industrielle : staging, tests qualité, survivorship
- EPCI, départements, régions en tables dédiées ; rapprochements Splink (SIRENE, BAN) avec `mdm.xref_*`
- APIs directement sur les vues `mdm` (jointures avec le datastore)
- Sélecteur territorial du portail branché sur ce référentiel
