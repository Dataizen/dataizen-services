# Writing a `.dolfin` canonical model

The `.dolfin` file is the canonical model in plain, human-readable form.
It is edited during design meetings, versioned like source code, and
compiled to Python via `dolfin2model.py`.

## Full syntax the compiler understands

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
  has name: one string
  has refExt: optional string

concept MainEntity:
  has localId: one string
  has subEntity: one SubEntity
  has status: optional SomeEnum
  has tags: at least 1 string
```

Cardinalities (compiler output between parentheses):

- `one T` → `T` (required)
- `optional T` → `Optional[T] = None`
- `at least 1 T` → `list[T]` (required, non-empty by convention)
- `at least N T`, `at most N T`, `exactly N T`, `between N M T` → `list[T]` with a comment noting the intended cardinality
- bare (no keyword) → `list[T] = field(default_factory=list)` (any, including zero)

Primitive types: `string` → `str`, `int` → `int`, `float` → `float`, `boolean` → `bool`. Any other name is treated as a forward reference to another concept.

## Design rules of thumb

1.  **Lift categorical free-text fields.** If a source uses free text for a closed set of values (`"active"`, `"inactive"`, ...), make it an enum. If the set is open, make it a small sub-concept with its own attributes.

2.  **Lift shared real-world entities.** If several top-level records refer to the same authority, category, or species, give that thing its own concept, not a copied string. This is where the pivot dedupes N spellings of the same reality into one canonical node.

3.  **External references.** Give any concept that has a stable public identity an optional `refExt` (or `taxonRef`, `wikidataRef`, ...) string field. Adapters can fill it with a resolvable IRI (GBIF, schema.org, Wikidata).

4.  **`optional` liberally.** Data is messy. A model with 50 required fields breaks on the first row. A model where the core identity is required and the rest is optional survives real-world data.

5.  **Dates as strings.** Dolfin has no native `date` type. Store ISO 8601 strings and be explicit about it. Downstream tools that want a `datetime` will parse cleanly.

6.  **Preserve provenance.** Add a `source` string field on records where the origin dataset matters. It is trivial to fill and priceless when debugging a downstream inconsistency.

## Iterative process

- **Round 1.** Look at one source file. Draft a `.dolfin` that captures its content faithfully.
- **Round 2.** Look at a second source in the same domain (a different provider, a different city). Adjust the model so both fit. This is where sub-concepts and enums earn their keep.
- **Round 3.** Check what open standards exist (Smart Data Models, INSPIRE, schema.org, DATEX II, GBIF, Wikidata). Align attribute names where the standard fits; add `refExt` fields where you can bind an entity to an external IRI.
- **Round 4.** Read the `.dolfin` out loud to a domain expert. If they can follow, you are done. If not, rename until they can.

## Worked examples in this repo

- `examples/trees.dolfin` — heritage-classified trees, with a taxonomy anchor (GBIF).
- `examples/pois.dolfin` — multilingual points of interest, with schema.org and Wikidata anchors.
- `examples/traffic.dolfin` — city-wide traffic KPIs, aligned partially to Smart Data Models `TrafficFlowObserved`.

Open each one, read it, then look at the matching `harmonize_*/model.py` to see the Python it compiles to.
