---
name: authoring-data-contracts
description: Use when building or planning a new or changed automation at Avenue Z that reads external data (API, MCP, CSV/file, LLM output) or emits a deliverable — any spec or plan that crosses a data boundary and needs a data contract. Symptoms: authoring a Schema or contract.yaml, adding @runtime.raw/input/output decorators, wiring the CI gate, or hitting a `contract lint`/`contract reconcile` failure ("unresolved schema ref", "Extra inputs are not permitted", "Field required").
---

# Authoring data contracts

## Overview

A data contract gives an automation two safety checks from one artifact: **runtime validation**
(did the vendor change the data under us?) and **static reconciliation** (did the code drift from
the design?). You author two kinds of file:

- a **Schema** — a named, versioned, standalone shape (`schemas/<platform>/<name>/<X.Y.Z>.yaml`)
- a **contract.yaml** — declares this system's `raw` / `inputs` / `outputs` boundary sets, each
  **referencing a schema by name — never inlining a shape**.

Then you decorate the boundary functions and let CI run `contract lint` + `contract reconcile`.

**The authored format is strict and not guessable — copy a template, don't invent keys.** Unknown
or mistyped keys are a hard load error (and the error text can mislead). The templates in
`references/templates/` are the fast path; the exact shapes are also in the Quick reference below.

## When to use

- A spec or plan for a new/changed automation names an input (API, MCP, file/CSV, LLM output) or a deliverable.
- You are adding `@runtime.raw` / `.input` / `.output` to code.
- `contract lint` or `contract reconcile` is failing and you need the correct shape.

Not for: Phase-2 `compat` / schema-semver authoring; editing `contract-core` itself.

## The workflow — it extends the superpowers spec→plan flow

This skill rides **alongside** superpowers `brainstorming` and `writing-plans` (brainstorming still
comes first). It adds three obligations, one per stage:

**Phase A — during the spec (brainstorming): emit `contract.yaml` + schema files next to the spec.**
1. List boundaries: each external read → an `input`; each deliverable → an `output`.
2. **Mediated source? (API / MCP / LLM) → it *also* gets a `raw` boundary** before the adapter. A
   file/CSV read is a single (normalized) boundary, no `raw`. See `references/boundary-decision.md`.
3. Pick `kind`: rows/columns → `tabular`; nested/JSON payload → `payload`.
4. **Author every schema from the *real* columns/shape — never placeholders.** The pilot matched on
   the first try across four verticals because the schema came from the real export.

**Phase B — during the plan (writing-plans): the plan lists the boundary decorators.**
- Name each decorator and its home: `@runtime.raw(...)` on the **true pre-cleaning read**
  (the `read_csv` / raw API return, *before* any strip/filter), `@runtime.input(...)`, `@runtime.output(...)`.
- **Every `raw` boundary ⇒ a companion `@pytest.mark.raw_drift("<name>")` test in the plan.** Omit it
  and `contract reconcile` fails with a category-D finding. This is not optional; set it up by default.
- Model a frame your **own code produces** under `outputs:` (warn-on-extra), not `inputs:`
  (silently-open) — else a forgotten column update is silent.

**Phase C — implement & verify.**
- Wire `load_runtime`, decorate, write the drift test. Copy `references/templates/runtime_wiring.py`
  (it includes the lazy build, the `CONTRACT_DISABLED` kill switch, and the absent-library fallback).
- Run `contract lint --contract contract.yaml --schemas schemas` and
  `contract reconcile --contract contract.yaml --package <pkg> --tests tests` — both green before done.
- **Adopt in `observe` first** (validate, never fail, log the observed shape) → read the event log →
  promote each boundary to `enforce`. This is the on-ramp; do not start at `enforce` on live data.

## Quick reference — the exact shapes

**Schema** `schemas/<platform>/<name>/<X.Y.Z>.yaml` (path, filename semver, and the dotted `schema:`
name must agree). Every schema needs `schema` + `version` + `kind` + exactly one of `fields`/`json_schema`:

```yaml
schema: tiktok.campaign_metrics      # <platform>.<name>, matches the directory
version: 1.0.0                        # semver; also the filename (1.0.0.yaml)
kind: tabular                        # tabular -> fields ; payload -> fields OR json_schema
fields:
  - name: spend
    type: float                      # string | int | float | bool | date | datetime
    required: true                   # default true
    nullable: false                  # default false
```

**Contract** `contract.yaml`. Top level is `system` + `version` (NOT `name`). Groups are `raw`,
`inputs`, `outputs` (plural). **Every boundary — including `raw` — needs a `schema:` ref.** Refs are
major-pinned `platform.name@major`:

```yaml
system: tiktok-brand-pulse           # NOT `name:`
version: 1.0.0
raw:                                 # only for mediated sources
  - name: tiktok_raw
    schema: tiktok.raw_report@1      # yes — raw is schema'd too (the per-call-site shape)
    source: {kind: api, format: json}
    mode: enforce
inputs:                              # plural
  - name: campaign_metrics
    schema: tiktok.campaign_metrics@1
    source: {kind: file, format: csv}
    mode: enforce
outputs:                             # plural
  - name: report
    schema: brandpulse.report@1
    sink: {kind: file, format: json}
    mode: enforce
```

| Field-type keywords | Where they apply |
| --- | --- |
| `enum` | string / int / bool |
| `minimum`, `maximum` | int / float |
| `min_length` (>= 1) | string |

## Common mistakes

| Symptom / mistake | Fix |
| --- | --- |
| `system: Field required`, `version: Field required` | Contract top level is `system:` + `version:`, not `name:`. |
| `Extra inputs are not permitted` on `input`/`output`/`name` | Groups are plural `inputs:`/`outputs:`; there is no top-level `name:`. Strict `extra="forbid"`. |
| `raw.0.schema: Field required` | **`raw` boundaries are schema'd too.** Author a per-call-site raw schema and reference it. |
| `LINT FAILED — unresolved schema refs` | Ref must be `platform.name@major` and the file must live at `schemas/<platform>/<name>/<semver>.yaml`. Flat `schemas/x.yaml` won't resolve. |
| "authored against a newer contract-core" hint on a file you just wrote | It's usually a **wrong/typo'd key**, not a version problem — strict keys surface with that hint. Check the key against a template. |
| `reconcile` category-D: "raw boundary declared but no drift test" | Add `@pytest.mark.raw_drift("<name>")` (name matches the raw boundary) in `tests/`. |
| Decorated a post-cleaning function as `raw` | Decorate the **true raw read** (before any strip/filter), or drift hides in your cleaning step. |
| Runtime built at import time; import crashes without the library | Use the lazy build + absent-library fallback in `references/templates/runtime_wiring.py`. |

## Files in this skill

- `references/boundary-decision.md` — input? raw? output? tabular vs payload — the decision tree.
- `references/strict-format-gotchas.md` — every strict-format landmine, with the exact error each throws.
- `references/templates/` — copy-edit these: `schema.tabular.yaml`, `schema.payload.yaml`,
  `contract.file-ingest.yaml`, `contract.mediated.yaml`, `drift_test.py`, `runtime_wiring.py`, `ci-gate.yml`.
- `references/worked-example.md` — a full automation authored end-to-end, lint + reconcile green.
