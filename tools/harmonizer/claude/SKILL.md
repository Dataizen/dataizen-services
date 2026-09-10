# SKILL, the pivot harmonizer pattern

A reusable method for harmonizing heterogeneous datasets against one or
more open standards, without losing semantic content and without
maintaining N x M mapping tables.

Developed by team LESL (Dolfin, Kereval, Askem) during the
**MIMathon Porto 2026**, validated on three open-data use cases:

- UC1, classified trees of Porto, with GBIF taxonomic alignment
- UC2, points of interest (Casas de Fado, petrol stations), with schema.org and Wikidata alignment
- UC4, city-wide traffic indicators, dual-publishing to Smart Data Models JSON-LD and DATEX II v3 XML

This document describes the method so it can be applied to a new
domain in a few hours.

---

## 1. When to use this pattern

Use it when **at least one** of these applies:

- You have **multiple source datasets** that describe the same kind of entity with different field names, units, structures, or spelling variants.
- You have **multiple consumer ecosystems** that expect different open standards (Smart Data Models, INSPIRE, DATEX II, schema.org, NGSI-LD), and you must serve them all without drift.
- The data has **format quirks**: multilingual fields, embedded formats (vCard, iCalendar), Python dict-literals in CSV cells, free-text values that hide structured information.
- You need the work to be **auditable**, **reproducible**, and **easy to extend** to the next dataset or the next output format.

Do NOT use it when:

- One source, one consumer, fixed schemas, no growth expected. Write a small script.
- An existing open standard already fits the source data without translation. Use it directly.
- The dataset is tiny and one-off (under ~20 records, never repeated). The structure overhead is not worth it.

---

## 2. The pattern in one diagram

```
        source A       source B       source C
           │              │              │
        adapter A      adapter B      adapter C
           │              │              │
           ▼              ▼              ▼
        ┌──────────────────────────────────────┐
        │ Canonical model (Dolfin pivot)       │
        │ + typed sub-entities                 │
        │ + external IRI references            │
        │ + closed enums                       │
        └──────────────────────────────────────┘
           │              │              │
        writer 1       writer 2       writer 3
           │              │              │
           ▼              ▼              ▼
        SDM JSON-LD    DATEX II      GeoJSON
        consumer       consumer       consumer
```

**N adapters in, M writers out.** Each new source adds one adapter.
Each new output adds one writer. The pivot stays small.

---

## 3. Step-by-step recipe

### Step 1, audit the data

Before writing a line of Dolfin, look at the data:

- Record count, column count, distinct values for each candidate enum field.
- Spelling variants of categorical fields (e.g. "ICNF", "ICNF (Instituto...)", "Instituto da Conservação ... (ICNF)" all denote the same authority).
- Format quirks: embedded vCard or iCalendar in CSV cells, Python dict-literals (single-quoted), multilingual fields as arrays of `{lang, value}`.
- Missing-data patterns: empty strings vs missing keys vs explicit "Unknown".

Quick Python to profile a CSV:

```python
import csv, ast
from collections import Counter
rows = list(csv.DictReader(open("data.csv")))
print("rows:", len(rows))
for col in ("category", "authority", "kind"):
    print(col, Counter(r[col].strip() for r in rows))
```

### Step 2, benchmark open standards

For every candidate canonical concept, check:

- **Smart Data Models** registry (https://smartdatamodels.org), look at `official_list_data_models.json`.
- Domain-specific standards: DATEX II for road traffic, INSPIRE for spatial data, schema.org for general semantic web, GBIF for biological taxonomy, Wikidata for cultural concepts.
- Decide one of three outcomes:
  - **align**: the standard fits, we adopt its attribute names and shapes,
  - **partial**: the standard fits some attributes, we extend with a local namespace for the rest,
  - **gap**: no standard fits, we define the model and document the gap as a candidate contribution.

UC1 was a gap (no SDM Tree), UC2 was an align (SDM PointOfInterest exists), UC4 was a partial (SDM TrafficFlowObserved is per-segment, our data is city-wide).

### Step 3, define the canonical model in Dolfin

Write a `<domain>.dolfin` file. A Dolfin model has:

```
package <http://your-namespace/uc/name>:
  dolfin_version "1"
  version "0.1.0"
  author "your team"
  description "one-paragraph rationale"

concept SomeEnum:
  one of:
    ValueA
    ValueB
    Unknown

concept SubEntity:
  has someAttr: one string
  has refExt: optional string

concept MainEntity:
  has localId: one string
  has subEntity: one SubEntity
  has somethingOptional: optional int
```

**Rules of thumb:**

- Lift every categorical free-text field to either an enum (closed set) or a typed sub-entity (small open set with attributes).
- Lift every shared real-world entity (Authority, Species, Category) to a separate concept, so multiple records can share one canonical node.
- Add an optional `<X>Ref` string attribute on entities that have stable external IRIs (taxon refs, schema.org class IRIs, Wikidata Q-IDs).
- Use `optional` liberally: data is messy, your model should not be brittle.
- Keep dates as ISO 8601 strings if Dolfin lacks a native date type; explicit serialization beats implicit conversion.

### Step 4, scaffold the harmonizer package

```
harmonize_<domain>/
├── __init__.py
├── __main__.py            ← CLI
├── model.py               ← @dataclass mirrors of the .dolfin concepts
├── transforms.py          ← clean_text, extract_count, match_keywords, Registry
├── jsonld.py              ← canonical JSON-LD writer (always include)
├── geojson_out.py         ← canonical GeoJSON writer (when geo is relevant)
├── <extra>.py             ← e.g. datex2.py, ngsi_ld.py, csv_out.py
├── README.md
└── adapters/
    ├── __init__.py
    ├── _template.py       ← skeleton for the next dataset
    └── <source>.py        ← one adapter per input dataset
```

`transforms.py` is portable across domains: copy it from any of the three reference implementations. It carries `clean_text`, `extract_count`, `match_keywords`, `Registry`.

### Step 5, the adapter contract

Every adapter file exposes exactly one function:

```python
def read(path: str | Path) -> Iterator[CanonicalEntity]:
    """Yield canonical-shaped instances from a source dataset."""
```

Inside the function:

- Parse the source file (CSV, GeoJSON, XML, JSON, whatever).
- For each row, build typed sub-entities (`Species`, `Authority`, `Address`, ...).
- Resolve enums via `match_keywords` and lookup tables (`category_map.json`).
- Dedupe shared entities via `Registry` so spelling variants collapse to one canonical instance.
- Yield the top-level canonical entity.

No writer logic, no external-API logic, no CLI logic in the adapter. It is purely a source-format-to-canonical translator.

### Step 6, write the writers

One writer per output format. Each writer:

- Takes an iterable of canonical entities.
- Emits the target format directly.
- Never looks at the source data.

For JSON-LD:

```python
from dataclasses import asdict

CONTEXT = {
    "@vocab": "http://your-ns/",
    "schema": "https://schema.org/",
    "yourField": "schema:matchingField",
    ...
}

def build_document(entities, base_id):
    return {"@context": CONTEXT, "@graph": [_to_node(e, base_id) for e in entities]}
```

For an XML format (DATEX II, INSPIRE, ...), use `xml.etree.ElementTree` with `register_namespace` to manage the default namespace cleanly. Pass attribute dicts via the `attribs` parameter to a small `_e(parent, tag, text=None, attribs=None, **kw)` helper.

For GeoJSON, flatten the canonical entity properties to dotted-key strings (`category.sourceLabel`, `address.streetName`) so non-LD tools (geojson.io, QGIS, Leaflet) can use the data directly.

**Two writers cannot drift.** They read the same canonical input. If one drifts, the bug is in the writer, not in a hidden mapping table.

### Step 7, external references

Wherever a concept has a global identity, attach a resolvable IRI:

- Biological species: GBIF (`https://www.gbif.org/species/<usageKey>`), NCBI Taxonomy, IPNI.
- Categories of things: schema.org class IRIs (`https://schema.org/Restaurant`), Wikidata Q-IDs.
- Geographic places: GeoNames IDs, Wikidata.

Implement the lookup as a cached resolver class:

```python
class GbifResolver:
    def __init__(self, cache_path):
        self.cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    def resolve(self, scientific_name):
        if scientific_name in self.cache:
            return self.cache[scientific_name]
        # call API, cache result (including misses), return entry
```

For small controlled vocabularies (POI categories, traffic event types), prefer an explicit JSON lookup file (`category_map.json`) over an API call. Auditable, no network dependency, easy to extend.

### Step 8, wire the CLI

A single CLI orchestrates everything:

```bash
python -m harmonize_<domain> \
    --adapter <source_name> \
    --input <path> \
    --output <output.jsonld> \
    --datex2 <output.xml> \         # optional, format-specific
    --geojson <output.geojson> \    # optional
    --base-id <iri_prefix>
```

The `__main__.py` loads the adapter module dynamically (`importlib.import_module`), reads entities, optionally enriches via external resolvers, then dispatches to each writer.

### Step 9, validate

Re-run on a second dataset without changing the core:

- New source, same domain: write only a new adapter.
- New consumer ecosystem: write only a new writer.
- Both core and earlier adapters/writers untouched.

If you cannot do this with the second dataset, the canonical model is too source-specific. Revisit step 3.

Check sanity metrics:

- record count before vs after (should match unless filtering is intentional),
- distinct entity counts (e.g. species, authorities) before vs after (often shrinks because of dedup),
- spot-check a handful of records by ID against the source.

### Step 10, ship

Package and publish:

- A page per use case (`sl-uc<n>.html`) with: hero, dataset audit, standards benchmark, canonical model in Dolfin, mapping table, run instructions, before/after diff, JSON-LD graph SVG, source code visible and downloadable, "what's next" list.
- A single tarball of the harmonizer (`sl-uc<n>-harmonize.tar.gz`).
- A Dolfin file deposit (`sl-uc<n>.dolfin`) served as `text/plain`.
- Slides in markdown (`sl-uc<n>-slides.md`) rendered via mSM (https://dolfin.fr/mSM or any markdown-slide tool).

---

## 4. Files you almost always need

- `<domain>.dolfin`: the canonical model.
- `harmonize_<domain>/model.py`: Python dataclasses mirroring the model.
- `harmonize_<domain>/transforms.py`: portable text helpers (copy verbatim from any reference implementation).
- `harmonize_<domain>/<writer>.py`: one per output format.
- `harmonize_<domain>/adapters/_template.py`: scaffolding for the next dataset.
- `harmonize_<domain>/adapters/<source>.py`: actual ingestion logic.
- `harmonize_<domain>/__main__.py`: CLI.
- `harmonize_<domain>/README.md`: how to run, how to extend.

Optional, depending on the domain:

- `category_map.json`: explicit lookup from source labels to canonical IRIs (UC2).
- An external resolver module: `gbif.py`, `wikidata.py`, ... (UC1).
- A second writer: `datex2.py`, `ngsi_ld.py`, ... (UC4).

---

## 5. References to live implementations

The three MIMathon Porto 2026 use cases follow this pattern exactly:

| | UC1 | UC2 | UC4 |
|---|---|---|---|
| Domain | Classified trees | Points of interest | City traffic |
| Standards stance | Gap (proposed) | Align (SDM exists) | Partial (extend SDM) |
| External backbone | GBIF Backbone Taxonomy | schema.org + Wikidata | SDM Transportation + DATEX II |
| Records | 238 | 58 | 2598 |
| Writers | JSON-LD, GeoJSON | JSON-LD, GeoJSON | JSON-LD, DATEX II XML, GeoJSON |
| Page | askem.eu/mimathon/sl-uc1.html | sl-uc2.html | sl-uc4.html |

Each page links the canonical `.dolfin` file, the full harmonizer source code, the source dataset, and the harmonized outputs. They are deliberately reproducible.

---

## 6. References

- **Dolfin** language: https://dolfin.fr, with full docs at https://dolfin.fr/docs and a tutorial.
- **Smart Data Models** registry: https://smartdatamodels.org, official list at https://github.com/smart-data-models/data-models.
- **DATEX II**: https://datex2.eu.
- **schema.org**: https://schema.org.
- **GBIF Backbone Taxonomy**: https://www.gbif.org/dataset/d7dddbf4-2cf0-4f39-9b2a-bb099caae36c, species match API at https://api.gbif.org/v1/species/match.
- **Wikidata**: https://www.wikidata.org.
- **mSM** slide player: https://askem.eu/mimathon/msm.html.
- **OASC MIMs**: https://oascities.org/minimal-interoperability-mechanisms/.

---

## 7. Authors and credits

Team LESL, MIMathon Porto 2026:

- **Lea** and **Eliott**, Kereval (https://www.kereval.com), software quality and interoperability validation.
- **Sattisvar**, Dolfin (https://dolfin.fr), ontology language and canonical-pivot tooling.
- **Louis**, Askem (https://askem.eu), method design and delivery.

This document and the reference implementations are released for reuse
in other harmonization projects.
