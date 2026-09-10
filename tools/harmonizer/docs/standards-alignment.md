# Standards alignment

A short field guide to the open standards you are likely to align against in this pattern. For each one, when to use it, what to link to, and where the shoe pinches.

## Smart Data Models (SDM)

- **What.** A community catalogue of harmonised NGSI-LD data models across smart-city, smart-agri, smart-energy and other verticals. Co-governed by OASC, FIWARE, TM Forum, IUDX.
- **Where to look.** [smartdatamodels.org](https://smartdatamodels.org), [official list JSON](https://github.com/smart-data-models/data-models/blob/master/specs/AllSubjects/official_list_data_models.json).
- **When it fits.** Whenever you can pick a matching entity type (`PointOfInterest`, `TrafficFlowObserved`, `WaterQualityObserved`, ...). Reuse the attribute names in your `jsonld.py` context; leave a namespaced local extension for what SDM does not cover.
- **When it doesn't.** No SDM matches your entity, or the closest SDM operates at a different granularity (`TrafficFlowObserved` is per-segment, you have city-wide aggregates). Two options: **partial** alignment (adopt what fits, extend with local terms), or **gap contribution** (draft a new SDM proposal, this is what team GEX did with `EnergyConsumptionObserved`).

## INSPIRE

- **What.** European directive for spatial data harmonisation. Themes: transport, hydrography, protected sites, land cover, ...
- **When it fits.** Your data is geospatial and you serve European public bodies.
- **Gotcha.** INSPIRE data models are heavy. For a hackathon-grade prototype, take a subset. For a production feed, mind the mandatory metadata.

## DATEX II

- **What.** European standard for road traffic and travel data exchange. XML-based, versioned (v3 is the current line), officially registered.
- **Where to look.** [datex2.eu](https://datex2.eu).
- **When it fits.** You publish mobility data to any European road authority or GPS-provider ecosystem. UC4 in this repo produces a structural DATEX II v3 projection.
- **Gotcha.** The spec is vast. A minimal `MeasuredDataPublication` is tractable. Full XSD schema validation is a separate, larger piece of work.

## schema.org

- **What.** A cross-domain vocabulary used by search engines and the wider web. `Restaurant`, `Museum`, `GasStation`, `Event`, `Place`, ...
- **When it fits.** Web-facing use cases: tourism, POIs, cultural sites, retail. schema.org classes are stable, dereferenceable, and understood by SEO tools out of the box.
- **How to bind.** Add a `schemaOrgRefs: list[string]` field on your Category concept, populate it with IRIs like `https://schema.org/Restaurant`. See UC2 for a worked example.

## GBIF Backbone Taxonomy

- **What.** The global authority for biological species names. Every species has a stable `usageKey` and a dereferenceable page at `gbif.org/species/<key>`.
- **When it fits.** Any dataset with organism names — trees, wildlife, biodiversity, protected species.
- **API.** [`species/match`](https://api.gbif.org/v1/species/match) does fuzzy matching. See UC1 (`harmonize/gbif.py`) for a cached resolver you can copy.

## Wikidata

- **What.** The largest general-purpose knowledge graph. Every concept has a Q-ID (`Q3338148` for "Casa de fado", `Q205495` for "filling station").
- **When it fits.** Culturally specific entities that schema.org does not model (traditional POI types, local monuments, region-specific practices), or as a secondary anchor next to schema.org.
- **How to bind.** Add a `wikidataRef: string` field. Wikidata Q-IDs are stable, cross-language, and machine-readable via SPARQL.

## NGSI-LD

- **What.** JSON-LD dialect used by FIWARE and OASC context brokers. Every entity has a URN identifier, typed attributes, and optional relationships.
- **When it fits.** Any smart-city pipeline where downstream systems will subscribe to updates via a context broker (Orion-LD, Scorpio, Stellio).
- **How to serialize.** The JSON-LD writer in this repo is close to NGSI-LD but not identical. Full NGSI-LD compliance is a bounded refinement of `jsonld.py`.

## OASC MIMs (Minimal Interoperability Mechanisms)

- **What.** A meta-framework: eight (and growing) documented mechanisms that a smart city should have, from data models (MIM2) to identity management (MIM6) to geospatial encoding (MIM7).
- **Where to look.** [oascities.org / minimal-interoperability-mechanisms](https://oascities.org/minimal-interoperability-mechanisms/).
- **Why care.** MIMs are the vocabulary the OASC community uses to describe compliance. A pipeline that satisfies MIM1, MIM2, MIM3 and MIM7 is legible to any OASC-adjacent stakeholder. UC3 in this repo maps each ranger to a specific MIM requirement.
