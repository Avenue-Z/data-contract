# The authoring skill and the spec→plan flow

The `authoring-data-contracts` skill (system design §5.5) makes writing a Schema + Contract the
default path for a new automation, so contracts happen without anyone being reminded — the bar R7
sets. This note explains how it plugs into the existing superpowers flow. The skill itself lives at
[`skills/authoring-data-contracts/`](../skills/authoring-data-contracts/SKILL.md).

## It extends the flow; it does not replace it

The superpowers `brainstorming` and `writing-plans` skills are unchanged. This is a **companion**
skill that rides alongside them — `brainstorming` still comes first. Integration is by convention and
by the skill's own trigger, not by editing the superpowers skills (they ship from a plugin cache and
are read-only). The skill adds exactly three obligations, one per stage:

| Stage | superpowers skill | What this skill adds |
| --- | --- | --- |
| Spec | `brainstorming` | The spec **emits `contract.yaml` + schema files** next to the design markdown — boundaries identified, schemas authored from the *real* shapes. |
| Plan | `writing-plans` | The plan **lists the boundary decorators** (`@runtime.raw/input/output`) and, for every `raw` boundary, its companion `@pytest.mark.raw_drift` test. |
| Build | (implementation) | Wire `load_runtime`, decorate, and get `contract lint` + `contract reconcile` green; adopt in `observe`, then promote to `enforce`. |

The two design-doc phrases in §5.5 map directly: *"a spec emits a contract.yaml alongside the
markdown"* is the Spec row; *"the plan includes the boundary decorators"* is the Plan row.

## When it fires

The skill's description triggers whenever a spec or plan for a new or changed automation names an
external input (API, MCP, file/CSV, LLM output) or a deliverable — i.e. the moment the work crosses a
data boundary. It does not try to pre-empt `brainstorming`; it activates as the spec/plan reaches I/O.

## Distribution — assume it is already installed

The skill's source of truth lives in this repo (matching the §10 topology: the skill ships from
`data-contract`). It is distributed through the Avenue Z marketplace. Neither the skill nor this repo
forces a download or nags about installing it — an author is assumed to have already synced the
avenue-z plugins. If a repo does not have it, sync the avenue-z marketplace once; nothing here gates
on that.

## What the skill carries for consumers

Per the closing note of [`consuming-repo-setup.md`](consuming-repo-setup.md), the skill is the home
for three consumer concerns, delivered as copy-edit templates under `references/templates/`:

- **§1** — pinning `contract-core` by `.git@<tag>` (>= v0.5.0) and the read token (`ci-gate.yml`).
- **§3** — the `CONTRACT_DISABLED` kill switch (honored automatically by `load_runtime`).
- **§4** — the absent-library no-op fallback (`runtime_wiring.py`).

## How R7 is measured

R7 (design §14) is the reason this skill exists and the bar it is judged against: dogfood on the next
N≥5 new automations and measure the contract-adoption rate **without nagging**. Adoption that needs a
human reminder means the skill failed; the threshold is <80% adopting a contract unprompted. The
skill's whole design bias — copy-edit templates over recall, a worked example proven green, the format
landmines pre-answered — serves that single number.
