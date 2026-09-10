# harmonize, urban tree harmonizer

Generic harmonizer for urban tree datasets, MIMathon Porto 2026 use case 01.
Reads any tree dataset via a small adapter, resolves species against
the GBIF Backbone Taxonomy, and emits JSON-LD conformant to the canonical
`Tree` model defined in `../trees.dolfin`.

## Run

```bash
python -m harmonize \
    --adapter porto \
    --input ../uc1-trees-porto.geojson \
    --output ../out/trees.jsonld \
    --base-id "http://mimathon.askem.eu/uc1/trees/" \
    --gbif-cache ../out/.gbif_cache.json
```

Flags:

- `--adapter` : module name under `harmonize.adapters`, e.g. `porto`.
- `--input` : source dataset path (the adapter knows the format).
- `--output` : destination JSON-LD file.
- `--base-id` : IRI prefix for tree `@id` values.
- `--gbif-cache` : on-disk cache so re-runs do not hit the API.
- `--no-gbif` : skip GBIF entirely (offline mode).

## Add a new dataset

Drop a `harmonize/adapters/<name>.py` file exposing a single function:

```python
def read(path) -> Iterator[Tree]:
    ...
```

The function yields `harmonize.model.Tree` instances. Look at
`harmonize/adapters/porto.py` for a worked example covering:

- field renaming (e.g. `especie` to `Species.scientificName`),
- enum normalization (e.g. age range strings to canonical values),
- entity extraction (e.g. parsing `"Conjunto arbóreo (12 exemplares)"`
  into `kind=TreeCluster, specimenCount=12`),
- authority deduplication (collapsing three spellings of "ICNF" into one
  `Authority` instance).

The core (model, GBIF resolver, JSON-LD writer) is dataset-agnostic and
needs no change.

## Output shape

A single JSON-LD document with a `@graph` of trees. Each tree has nested,
typed fragments for `Species`, `Location`, `Classification` (with its
`Authority` and `LegalAct`). The `@context` aligns to:

- `dwc:scientificName`, `dwc:vernacularName` (Darwin Core),
- `geo:lat`, `geo:long` (WGS84 vocabulary),
- a local namespace for `Tree`, `Classification`, etc.,
  ready to be reissued under a Smart Data Models context once the
  `dataModel.ParksAndGardens/Tree` proposal is accepted.
