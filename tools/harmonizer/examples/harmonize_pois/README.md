# harmonize_pois, urban POI harmonizer

Harmonizer for points-of-interest datasets, MIMathon Porto 2026 use case 02.
Reads any POI dataset via a small adapter, aligns categories against
schema.org and Wikidata via a category map, and emits JSON-LD plus
optional GeoJSON conformant to the canonical `PointOfInterest` model
defined in `../pois.dolfin`.

## Run

```bash
python -m harmonize_pois \
    --adapter porto_pois \
    --input ../uc2-pois-casas-de-fado.csv \
    --output ../out/pois.jsonld \
    --geojson ../out/pois.geojson \
    --base-id "http://mimathon.askem.eu/uc2/pois/"
```

Flags:

- `--adapter` : module name under `harmonize_pois.adapters`, e.g. `porto_pois`.
- `--input` : source dataset path.
- `--output` : destination JSON-LD file.
- `--base-id` : IRI prefix for POI `@id` values.
- `--geojson` : also emit a GeoJSON FeatureCollection for GIS tools.

## Add a new dataset

Drop a `harmonize_pois/adapters/<name>.py` file exposing a single function
`read(path) -> Iterator[PointOfInterest]`. Look at
`harmonize_pois/adapters/porto_pois.py` for a worked example covering:

- multilingual labels, descriptions, categories,
- Python dict-literal parsing (CitySDK quirk),
- vCard 2.1 address and contact extraction,
- category alignment via `category_map.json` to schema.org and Wikidata.

Extend `category_map.json` with new source labels as needed:

```json
{
  "<source label>": {
    "schemaOrgRefs": ["https://schema.org/SomeType", ...],
    "wikidataRef": "https://www.wikidata.org/entity/Q...."
  }
}
```

## Output shape

JSON-LD with `@graph` of POIs. Each node:

- `name` and `description` are arrays of language-tagged literals
  (`{@language, @value}`), aligned to `schema:name` / `schema:description`.
- `category` is a typed `Category` carrying both the `sourceLabel`
  observed in the data and resolved IRIs against `schema.org` and
  Wikidata.
- `address` and `contact` use schema.org-aligned property names so
  consumers can map to `schema:PostalAddress` / `schema:ContactPoint`
  trivially.

The GeoJSON output flattens these to dotted-key properties
(`name_pt`, `category.sourceLabel`, `address.streetName`...) for non-LD
tools.
