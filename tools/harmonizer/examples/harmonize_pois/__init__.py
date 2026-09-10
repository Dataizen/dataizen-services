"""Generic point-of-interest harmonizer, MIMathon Porto 2026 UC2.

Same architecture as the trees harmonizer: a dataset-agnostic core
(model, JSON-LD/GeoJSON writers, schema.org category resolver), plus
one adapter per source dataset.
"""
