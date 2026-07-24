# Authoring skill (§5.5) — Design

**Date:** 2026-07-24
**Status:** Approved for build (via superpowers:writing-skills)
**Owner:** Paul Ramirez / Engineering
**Implements:** system design §5.5; closes the risk named in §14 R7.

## 1. Purpose

Make writing a Schema + Contract for a new automation the **default, low-friction path**, so new
automations get contracts without anyone being nagged. R7's bar is explicit and measurable:
*adoption that needs a human reminder = skill failure* (§14, threshold <80% unprompted). The skill
is measured by felt friction, not feature count — bias to minimum friction over completeness.

## 2. Shape and integration

A **companion process skill**, not a replacement for the superpowers flow. The superpowers
`brainstorming` / `writing-plans` skills live in a read-only plugin cache and are **not modified**;
"extends the spec→plan flow" (§5.5) is realized by convention + description-trigger:

- **Source of truth** lives in this repo at `skills/authoring-data-contracts/`, matching the §10
  topology ("the skill … ships from `data-contract`").
- **Distribution** is via the Avenue Z marketplace. Neither the skill nor the docs force an install
  or nag about one — they assume the author has already synced the avenue-z plugins.
- **Trigger:** fires when a new or changed automation *reads external data or emits a deliverable* —
  the moment a spec/plan touches a data boundary. It does not try to out-trigger `brainstorming`;
  the rule stays "brainstorming first," and this skill activates as the spec/plan reaches I/O.

## 3. Workflow taught (mapped onto spec→plan→implement)

**A. During the spec (brainstorming) — emit `contract.yaml` + schemas alongside the markdown**
(the §5.5 "spec emits a contract.yaml" deliverable).
- Each external read → an `input` boundary; each deliverable → an `output` boundary.
- Mediated source (API/MCP/LLM) → *also* a `raw` boundary before the adapter (§7, decision #4).
  File/CSV ingest → single (normalized) boundary only.
- Tabular (rows/cols) → `kind: tabular`; nested/JSON payload → `kind: payload`.
- **Author schemas from the real columns/shape, never placeholders** — the pilot matched on the
  first try across four verticals precisely because schemas came from the real export (§15 gate).

**B. During the plan (writing-plans) — the plan lists the boundary decorators**
(the §5.5 "plan includes the boundary decorators" deliverable).
- `@runtime.raw(...)` on the *true pre-cleaning read* (§15 finding 6), `@runtime.input(...)`,
  `@runtime.output(...)`.
- **Every `raw` boundary ⇒ a companion `@pytest.mark.raw_drift("<name>")` test, listed in the
  plan** — omission is a `reconcile` category-D failure (§14 R2). Set up by default.
- Producer-internal frames modeled under `outputs:` (warn-on-extra), not `inputs:` (§15 finding 8).

**C. Implement & verify.** Wire `load_runtime`, decorate, write the drift test → `contract lint` +
`contract reconcile` green → adopt in `observe`, read the event log, promote to `enforce`.

## 4. Hard constraints the skill honors and teaches

- Authored files are **strict** (`extra="forbid"` on Schema/Field/Contract/BoundarySpec): an unknown
  or mistyped key is a hard load error. Files carry `format_version: v1` (a missing stamp reads v1).
- A schema is a **named, versioned, standalone shape** at `schemas/<system>/<name>/<X.Y.Z>.yaml`; a
  contract declares `raw`/`inputs`/`outputs` boundary sets that **reference schemas by name, never
  inline a shape**.
- A schema sets **exactly one** of `fields` / `json_schema`; `json_schema` only when `kind: payload`.
- Output must compile to valid ODCS and pass `contract lint --contract <c> --schemas <dir>`.
- Any `raw` boundary requires the `@pytest.mark.raw_drift("<name>")` companion test, or
  `contract reconcile` emits category-D.
- Consumers pin with the `.git@<tag>` URL form at **>= v0.5.0** (the gate's first release).
- The skill carries the three items the consuming-repo doc assigns it (`docs/consuming-repo-setup.md`
  closing note): **§1** pin + deploy token, **§3** the `CONTRACT_DISABLED` kill switch, **§4** the
  absent-library no-op fallback.

## 5. Files delivered

```
skills/authoring-data-contracts/
  SKILL.md                          # tight workflow + the 3 phases; frontmatter trigger
  references/
    boundary-decision.md            # input? raw? output? tabular vs payload — decision tree
    strict-format-gotchas.md        # extra=forbid, exactly-one-of, kind gates json_schema, format_version
    templates/
      schema.tabular.yaml
      schema.payload.yaml
      contract.file-ingest.yaml     # single-boundary (the common case)
      contract.mediated.yaml        # raw + input + output (two-boundary)
      drift_test.py                 # the raw_drift companion
      runtime_wiring.py             # load_runtime + decorators + absent-library fallback + kill switch
      ci-gate.yml                   # reusable-workflow call, same-tag rule, marker registration
    worked-example.md               # full sample walked end-to-end (mirrors the criterion-1 proof)
docs/authoring-skill-and-spec-plan-flow.md   # short "how it plugs into spec→plan" note
```

The templates exist so authoring is **copy-edit, not recall** — the primary friction lever for R7.

## 6. Verification (success criterion 1)

Create a throwaway sample automation in scratch, follow the skill's own steps against it, and run
`contract lint` + `contract reconcile` to green (no gating findings). `worked-example.md` mirrors that
same sample, so the skill ships with a proven, reproducible example rather than an asserted one.

## 7. Non-goals

- Not editing or forking the superpowers skills.
- Not building marketplace plumbing in this repo (source-of-truth only; assume synced).
- Not covering Phase 2 `compat` / schema-semver authoring — out of R7's scope.
