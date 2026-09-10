"""Generic urban-tree harmonizer, MIMathon Porto 2026 UC1.

Core (model, GBIF resolver, JSON-LD writer) is dataset-agnostic. To
harmonize a new dataset, write an adapter exposing a `read(path)` callable
that yields canonical-shaped trees, and pass it via the CLI.
"""
