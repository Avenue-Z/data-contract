# Strict-format gotchas

Authored files are **strict**: `extra="forbid"` on Schema, Field, Contract, and BoundarySpec. A key
`contract-core` does not recognise is a **hard load error**, not a silently-dropped line. This is a
feature (a typo'd `requird:` fails loudly instead of disabling a check) — but it means you cannot
guess keys. Each landmine below is a real error an agent hit authoring from scratch.

## The keys are not what you'd guess

| You might write | Correct | Error if wrong |
| --- | --- | --- |
| `name:` at contract top level | `system:` | `system: Field required` + `name: Extra inputs are not permitted` |
| (no version) | `version:` (semver) | `version: Field required` |
| `input:` / `output:` groups | `inputs:` / `outputs:` (plural) | `Extra inputs are not permitted` |
| `raw` with no schema | `raw` **with** a `schema:` ref | `raw.0.schema: Field required` |
| `schema: my_schema` | `schema: platform.name@1` (major-pinned) | `unresolved schema refs` |
| a bare `fields:` file (no header) | `schema:` + `version:` + `kind:` + `fields:` | `schema/version/kind: Field required` |

## The misleading version hint

A strict-key rejection often prints:

> The file was likely authored against a newer contract-core. Upgrade the pin, or author the file
> against 0.1.0. See CHANGELOG.md.

On a file **you just wrote**, this is almost always a **wrong or misplaced key**, not a version
mismatch. `format_version` only bumps when the *meaning* of an existing key changes. Check the
offending key (the `loc` before the colon) against a template before touching your pin.

## Schema body rules

- **Exactly one** of `fields:` or `json_schema:`. Setting both, or neither, fails:
  `schema must set exactly one of fields or json_schema`.
- `json_schema:` is allowed **only** when `kind: payload`. On a `tabular` schema it fails:
  `json_schema is only allowed when kind == 'payload'`.
- Field types are exactly: `string | int | float | bool | date | datetime`. Nothing else.
- Field defaults: `required: true`, `nullable: false`. State them only when you differ, or for clarity.

## Value constraints are checked at load, and adding one is a *major* bump

Optional per-field: `enum`, `minimum`, `maximum`, `min_length`. They apply only to the types below,
only to non-null values (`nullable` is the only null gate), and are checked for **satisfiability**
when the schema loads — an unsatisfiable one is rejected outright.

| Constraint | Applies to | Rejected examples |
| --- | --- | --- |
| `enum` | string / int / bool | `enum: []` (admits nothing); values not matching the type |
| `minimum` / `maximum` | int / float | `minimum: 5, maximum: 1` (empty interval); `minimum: 0.5` on an int; `minimum: true` |
| `min_length` | string | `min_length: 0` or negative (no-op) |

Adding a constraint to a schema is a **breaking** change → new **major** version. Do not add one to a
published `X.Y.Z` in place.

## `source` / `sink` are optional freeform hints — don't agonize

On a boundary, `source:` and `sink:` are **optional** and **not validated** — they are provenance
documentation. Any `kind` value is accepted; there is no fixed vocabulary and no dedicated `mcp`
type to hunt for. Use whatever reads clearly and omit them if you like:

```yaml
source: {kind: mcp}                    # or {kind: api, format: json} / {kind: file, format: csv} / {kind: llm}
# a boundary with no source/sink at all also lints fine
```

## Naming — hyphens are fine

`<platform>` and `<name>` in the dotted `schema:` id may contain hyphens or underscores; both
resolve (`foo-bar.baz@1` works). Just keep the dotted name, the directory path, and the filename
semver in agreement. Don't mangle a hyphenated system name to make a schema id — it isn't required.

## Directory layout the resolver requires

```
schemas/
  <platform>/
    <name>/
      1.0.0.yaml      # filename is the exact semver; the dotted `schema:` inside is <platform>.<name>
      2.0.0.yaml      # a change is a NEW version file, never an edit in place
```

`contract lint --schemas <dir>` only considers files whose stem parses as a semver, so `latest.yaml`
or `_template.yaml` are skipped — but a real schema at a flat path (`schemas/campaign_metrics.yaml`)
will **not resolve** and lint fails with `unresolved schema refs`.
