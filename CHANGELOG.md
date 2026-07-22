# Changelog

All notable changes to `contract-core` are recorded here. This file is the canonical
release notes: `docs/consuming-repo-setup.md` tells consumers to read them before moving a
pin, and a release is an annotated git tag with no package-index page to carry notes.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

`contract-core` is **pre-1.0**. Under 0.x semantics a **minor** bump may carry breaking
changes to the public API or the authored format. Read the entry before moving a pin.

## [Unreleased]

## [0.2.0] — unreleased, pending tag

### Added

- **Value constraints on schema fields** — `enum`, `minimum`, `maximum`, `min_length`.
  They compile to Pandera checks, JSON Schema keywords, and the ODCS export, and they
  hard-fail through the existing `observe`/`warn`/`enforce` ladder like structural drift.
  A violation reports the constraint, how many rows broke it, and up to three samples.
- Applicability is checked when the schema loads: `minimum`/`maximum` on `int`/`float`,
  `min_length` on `string`, `enum` on `string`/`int`/`bool` with values matching the
  declared type. A `bool` is not accepted as an `enum` value on an `int` field, nor as a
  `minimum`/`maximum` — Python treats `True` as `1`, and a bound that silently means `1`
  is not what the author wrote. On an `int` field a bound must be a whole number:
  `minimum: 0.5` is rejected (it means `1`, which is not what it says), while an integral
  `minimum: 1.0` is accepted and stored as `1`.
- Satisfiability is checked, not just applicability. Five ways to author a constraint that
  can never do what it appears to say are now rejected at load rather than failing every
  row at runtime: an empty `enum`, an empty interval (`minimum: 5, maximum: 1`), a
  `min_length` below 1, an `enum` disjoint from its own bounds
  (`enum: [0, 1]` with `minimum: 5`), and the `bool` and fractional-bound cases above. A
  *partial* overlap between an `enum` and its bounds is legitimate narrowing, not an error.
  This list is exhaustive — there is no general satisfiability solver behind it.
- `contract lint` now validates **every** schema file it can see, not only the ones the
  given contract references, and reports unparseable or unreadable files as diagnostics
  rather than propagating a traceback.

### Changed

- **BREAKING — `FieldDiff` gained a `"value"` variant of `problem`.** Code matching
  exhaustively on `problem` will see a value it has not seen before.
- **BREAKING — `FieldDiff` gained three fields**: `constraint`, `violating_rows`, and
  `samples`. They are `None`/empty on every structural diff. `field`, `expected`,
  `observed` and `problem` keep their meanings.
- **The ODCS export no longer emits `required`.** ODCS documents that key as null
  semantics ("may contain Null values"), not presence, so this project's presence flag
  did not belong in it. Null tolerance is now a `nullValues` quality rule, and an `enum`
  becomes an `invalidValues` rule. Presence is not exported — ODCS has no unambiguous slot.
- **BLAST RADIUS — the ODCS document changes for schemas that did not change.** The two
  bullets above are not scoped to constrained fields: `required` disappears from *every*
  property in *every* schema, and *every* non-nullable field grows a `nullValues` quality
  rule, whether or not that schema declares a single constraint. Regenerating ODCS for an
  untouched schema produces a different document, so a consumer diffing exported documents
  will see churn on schemas nobody edited. Concretely, for a field
  `{name: prompt, type: string, required: true}`:

  ```diff
  - {"name": "prompt", "logicalType": "string", "required": true}
  + {"name": "prompt", "logicalType": "string",
  +  "quality": [{"type": "library", "metric": "nullValues", "mustBe": 0}]}
  ```

  A field that is `required: true, nullable: true` now exports `{name, logicalType}` and
  nothing else: null tolerance is true so no rule fires, and presence has no ODCS slot.
  **Presence is no longer representable in the ODCS export at all** — it lives only in the
  authored schema. If you consume presence from exported ODCS, read it from the schema
  instead.

### Notes for consumers

- **Adding a constraint to a schema is a BREAKING change: bump the schema's MAJOR
  version.** A constraint can fail data that previously passed, and a `@1` pin resolves to
  the highest matching minor — so publishing constraints in a minor would reach every
  running consumer on its next resolve. Adopt a constraint-bearing major with the boundary
  in `observe`, read the event log, then promote to `enforce`.
- Constraints skip nulls. `nullable` remains the only null gate.
- `min_length: 1` rejects `""` but accepts `"  "`. A non-blank check needs `pattern`, which
  is not implemented yet.

## [0.1.0] — 2026-07-21

First installable release. Before this, `contract-core` existed only as an editable local
path, so no other repo could depend on it (risk R9).

### Added

- **A curated public API.** `contract_core` now exports exactly five names —
  `load_runtime`, `ContractRuntime`, `ContractViolation`, `FieldDiff`, `__version__` — and
  declares `__all__`. A frozen-surface test fails if that set changes, so a break must be
  deliberate and reviewed rather than silent.
- **`load_runtime(contract_path, *, schema_paths, enabled)`** — builds a runtime from a
  contract file, or returns a disabled no-op runtime.
- **`ContractRuntime.disabled(label)`** — a no-op runtime whose `raw`/`input`/`output` are
  the identity decorator. It performs no validation, no schema resolution and **no file
  I/O**, and writes exactly one line to `sys.stderr` at construction naming the trigger.
  Deliberately not a `logging` record: the guarantee is that the line's absence means
  validation is on, and a consumer's logging configuration can delete a record.
- **`CONTRACT_DISABLED` kill switch.** On iff present and its value, stripped and
  lowercased, is not one of `""`, `"0"`, `"false"`, `"no"`, `"off"`. So `=1`/`=true`/`=yes`/
  `=on` disable; `=0`/`=false`/`=no`/`=off`/empty/unset leave validation enabled — the
  values name the state of *the switch*, not of validation. **"Off always wins"** —
  application code passing `enabled=True` cannot override the env var.
- **Consumer documentation** — `docs/consuming-repo-setup.md` covers the git-tag pin, the
  deploy-token prerequisite, the kill switch, and the absent-library fallback pattern.
- **A release procedure** in `CONTRIBUTING.md`.

### Changed

- **Version `0.0.1` → `0.1.0`**, and a test now fails if `__version__` skews from the
  version declared in `pyproject.toml` (read from the file, so it holds on a dev machine
  with a stale editable install too).

### Notes for consumers

- **Deep module paths are private.** `contract_core.runtime`, `.errors`, `.contract`,
  `.resolver`, `.schema`, `.events`, `.types`, `.families`, `.vendor`, `.compile.*` and
  `.cli` may change without a major bump. The list is exhaustive and includes `.runtime`
  and `.errors`, where the exported names are defined — import the five public names from
  `contract_core` itself, not from the module they live in. Run the CLI via the `contract`
  console script.
- **No auto-degrade.** A missing or malformed contract file raises; it never silently
  disables validation.
- `EventLog` is deliberately *not* exported and `load_runtime` takes no `event_log`
  parameter — the event-log sink abstraction is unbuilt, and exporting either would promise
  a hook that does not exist.
- `schema_paths` defaults to `("schemas",)`. The signature is stable, but if a central
  schema registry path is later prepended to that default, a different schema may resolve —
  that will be called out as a behavior change here.

[Unreleased]: https://github.com/Avenue-Z/data-contract/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Avenue-Z/data-contract/releases/tag/v0.1.0
