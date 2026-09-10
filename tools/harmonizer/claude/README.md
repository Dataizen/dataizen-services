# `claude/` · AI-assisted onboarding

Open this repo in an AI coding assistant (Claude Code, Cursor, or any
tool that can read local files). Point it at this folder and give it
the goal: **onboard my dataset to the pivot harmonizer pattern**.

## Handoff prompt (copy-paste this)

> I want to harmonize a dataset using the pivot harmonizer pattern in
> this repo. Please:
>
> 1. Read `SKILL.md` at the repo root, and skim `docs/pattern.md`,
>    `docs/writing-a-dolfin.md`, `docs/standards-alignment.md`.
> 2. Look at the three worked examples under `examples/` to see how a
>    real `.dolfin` + adapter + writer look together.
> 3. Then help me onboard my source file at `<path/to/my/file>`.
>
> For step 3 in detail:
>
> - Start by auditing my source: record count, distinct values per
>   candidate enum field, spelling variants, format quirks.
> - Benchmark existing open standards (Smart Data Models, INSPIRE,
>   DATEX II, schema.org, GBIF, Wikidata) and recommend align /
>   partial / gap for each candidate canonical concept.
> - Propose a first `<domain>.dolfin` model. Iterate with me.
> - When the model is stable, run
>   `python3 dolfin2model.py <domain>.dolfin harmonize_<domain>/model.py`
>   to generate the Python dataclasses.
> - Scaffold `harmonize_<domain>/` from `template/` and drop the
>   compiled `model.py` in.
> - Customise `jsonld.py` `CONTEXT` to align with the standards we
>   selected.
> - Write my first adapter under `adapters/<source>.py`, inspired by
>   `examples/harmonize_pois/adapters/porto_pois.py` (the messiest of
>   the three, covers multilingual + vCard + Python dict-literals).
> - Run and show me the harmonized output.

## What the assistant has to work with

- **`../SKILL.md`** : the 10-step method, the north star.
- **`../docs/pattern.md`** : one-diagram summary of the pattern.
- **`../docs/writing-a-dolfin.md`** : the Dolfin syntax, design tips.
- **`../docs/standards-alignment.md`** : field guide to SDM, DATEX II, schema.org, GBIF, Wikidata, NGSI-LD, OASC MIMs.
- **`../examples/`** : three complete runnable pipelines to imitate.
- **`../template/`** : the starter kit to clone into a new domain.
- **`../dolfin2model.py`** : the compiler.

## Roles reminder

- **`.dolfin`** = human-readable canonical model, edited during design.
- **`model.py`** = machine-executable mirror, generated from the `.dolfin` by the compiler. Don't edit by hand.
- **Adapters** parse messy sources and yield canonical instances. Source-specific normalisation lives here.
- **Writers** render canonical instances to a target format. Never read source data.
- **`transforms.py`** = portable text helpers (`clean_text`, `extract_count`, `match_keywords`, `Registry`), reused across adapters unchanged.
