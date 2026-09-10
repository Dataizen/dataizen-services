# harmonize_traffic, city traffic harmonizer

Harmonizer for city-wide traffic observation datasets, MIMathon Porto
2026 use case 04. Reads any traffic dataset via a small adapter, and
emits **three derived outputs from one canonical record**:

- Smart Data Models JSON-LD (semantic, NGSI-LD friendly)
- DATEX II v3 XML (structural projection, measured-data publication shape)
- GeoJSON (FeatureCollection with city centroid points, for GIS tools)

## Run

```bash
python -m harmonize_traffic \
    --adapter tomtom \
    --input ../uc4-traffic-tomtom.csv \
    --output ../out/traffic.jsonld \
    --datex2 ../out/traffic.datex2.xml \
    --geojson ../out/traffic.geojson \
    --base-id "http://mimathon.askem.eu/uc4/traffic/"
```

Flags:

- `--adapter` : module name under `harmonize_traffic.adapters`, e.g. `tomtom`.
- `--input` : source dataset path.
- `--output` : destination JSON-LD file.
- `--base-id` : IRI prefix for observation `@id` values.
- `--datex2` : also emit DATEX II v3 XML.
- `--geojson` : also emit a GeoJSON FeatureCollection.

## Add a new dataset

Copy `harmonize_traffic/adapters/_template.py` to a new file under
`harmonize_traffic/adapters/<name>.py`, implement
`read(path) -> Iterator[TrafficObservation]`, and run with
`--adapter <name>`.

See `harmonize_traffic/adapters/tomtom.py` for a worked example over
TomTom's city-wide aggregated indicators (`TrafficIndexLive`,
`JamsLengthInKms`, `JamsCount`, `TravelTimePer10KmsMins`, ...).

## DATEX II output, intentionally a projection

DATEX II v3 is a vast spec. The XML produced here uses the right
namespaces, the right top-level shapes (`d2LogicalModel`,
`payloadPublication[xsi:type=MeasuredDataPublication]`,
`siteMeasurements`, `measuredValue`, `basicData[xsi:type=...]`), and
correct units (ISO 8601 duration, KILOMETRES, ...). It is not claimed
to be a fully schema-validated DATEX II 3 document; the goal is to
demonstrate that a canonical pivot can fan out cleanly into DATEX II
without compromising semantic content, and to make the path to full
compliance obvious.
