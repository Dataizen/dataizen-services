# The pivot harmonizer pattern

## The problem

Every dataset has its own dialect. Every consumer expects its own standard. Without a shared semantic pivot, teams end up maintaining **N × M mappings** between N sources and M target formats. That grid drifts silently, breaks under new sources, and duplicates parsing logic in every corner.

## The pattern

Pick one **canonical model**, written in a language that both humans and machines can read. In this repo, that language is [Dolfin](https://dolfin.fr).

- Each **source** gets one **adapter**: a small file that parses the raw format and yields canonical instances.
- Each **target format** gets one **writer**: a small file that reads canonical instances and emits the target shape.
- The **pivot** stays small. It only carries the model, not the parsing logic and not the rendering logic.

```
sources → adapters → canonical (Dolfin) → writers → consumers
```

New source: one new adapter. New consumer: one new writer. **N + M files instead of N × M**. The economics change.

## Why this works with AI in the loop

Large language models are strong at proposing mappings from one field name to another, and weak at guaranteeing consistency across an entire dataset. This pattern splits the job:

- **AI proposes** mappings during design. Human accepts, edits, or rejects.
- **Deterministic code** executes. The writers are pure functions of the canonical instances.
- **The canonical model** is the anchor the AI cannot drift away from.

The three example harmonizers in `examples/` are all-deterministic today. Nothing prevents adding an AI-driven adapter that reads a new source and proposes a `.dolfin` extension. The Knowledge Base pattern from team GEX's [CityData Harmonizer](https://github.com/GreenEarthX/city_data_harmonizer) is one way to make that reliable at scale.

## Anti-patterns

- **Merging adapter logic into the writer.** Keep them separate. A writer that reads source fields directly is a lie: it says "I emit canonical data" but actually depends on a specific source layout.
- **Encoding source-specific normalization in `model.py`.** The model is the pivot. Normalization (`normalize_age`, `parse_vcard`, ...) is source-specific and belongs to the adapter.
- **Skipping the `.dolfin` because "it's just documentation".** The `.dolfin` is the artefact the domain expert can read. Skipping it means the design lives only in Python, which the business cannot audit.

## When not to use this

- One source, one consumer, both stable: write a script and move on.
- The source already matches an open standard: use the standard directly, no pivot needed.
- The dataset is tiny and one-off: the structure overhead is not worth it.
