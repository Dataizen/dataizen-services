"""Generic traffic-observation harmonizer, MIMathon Porto 2026 UC4.

Same architecture as UC1/UC2: a dataset-agnostic core (model,
JSON-LD/DATEX II/GeoJSON writers), plus one adapter per source.
The two output formats are derived from the same canonical record,
so DATEX II and Smart Data Models stay in sync by construction.
"""
