# Value constraints — declarative, portable, at the boundary

**Status:** designed 2026-07-21, unimplemented.
**Closes:** most of §15 item 4 (the value-check enrichment gap). Narrows what remains of it.
**Parent spec:** [2026-07-16-data-contract-system-design.md](2026-07-16-data-contract-system-design.md)
— read decision #1 (Portable Core), decision #2 (inputs open / outputs complete), §4.1 and §5.2.

## 1. The problem

`to_pandera` emits presence, type, and nullability. The runtime applies exactly that. So a boundary
today catches *structural* drift and nothing else: the pilot's likely real corruption — sentiment
outside `[-1, 1]`, `is_owned ∉ {0, 1}`, negative ranks, an empty `brand` — passes validation and
flows downstream.

That is the "silently misses the real bugs" half of the §15 gate. Structural drift is loud; nonsense
values are silent.

## 2. Scope

**Ships:** four declarative constraints — `enum`, `minimum`, `maximum`, `min_length` — authored on a
field, compiled to **both** Pandera and JSON Schema, enforced through the existing mode ladder.

**Deferred:** the Python-side hook for cross-field checks and custom validators. It has no caller
today. An extension point designed against hypothetical needs is an extension point shaped wrong, and
this one would be public surface. §15 item 4 stays open, narrowed to just that hook.

**Unchanged:** `coerce=False` and the R8 family check. Nothing here mutates data to make it pass.

The four constraints are exactly what §15 item 4's four named examples require. That is the reason
the list is four long and not longer.

## 3. Amendment to decision #1 (Portable Core)

The principle stands; its boundary moves.

Decision #1 currently groups "ranges, regex, cross-column checks, custom validators" as non-portable,
on the grounds that they cannot be pushed into a cross-language schema. That is true of the last two
and false of the first two: `minimum`, `maximum`, `minLength`, `enum`, and `pattern` are all standard
JSON Schema 2020-12, and Ajv validates them.

The line as it should read:

- **Portable — part of the shared contract.** Presence, type, nullability, and the value constraints
  a JSON Schema can express. These compile to both targets, so `compat` reasons over them and the JS
  SDK (R6) enforces them.
- **Not portable — Python-side local enrichment.** Cross-field and cross-column relationships, and
  custom validators. These cannot cross the language boundary. This is the principle's real content.

Leaving ranges on the non-portable side would mean every consuming repo re-authors "sentiment is
between -1 and 1" in Python, and the JS SDK validates less than the schema actually knows.

## 4. Authored format

Constraints are optional keys on a field. Every existing schema stays valid; this is additive at the
format level.

```yaml
# schemas/peec/prompts_export/1.1.0.yaml
schema: peec.prompts_export
version: 1.1.0
kind: tabular
fields:
  - name: sentiment
    type: float
    minimum: -1.0
    maximum: 1.0
  - name: is_owned
    type: int
    enum: [0, 1]
  - name: rank
    type: int
    minimum: 1
  - name: brand
    type: string
    min_length: 1
```

**Schemas are immutable (§4.1), so adding a constraint is a new schema version.** A consumer pinned
to `1.0.0` is unaffected until it moves the pin — which is the point of pinning, and means this
change cannot break a running system by itself.

### 4.1 Applicability, enforced at load

A constraint on a type that cannot carry it is an authoring error, and it fails at
`Schema.from_yaml` — so `contract lint` rejects it, not production:

| Constraint | Valid on | Rejected because |
| --- | --- | --- |
| `minimum`, `maximum` | `int`, `float` | a bound on a string has no defined meaning here |
| `min_length` | `string` | ditto, inverted |
| `enum` | any type | — |

`enum` additionally requires a non-empty list whose values match the declared type. `enum: ["0", "1"]`
on an `int` field is accepted by a naive implementation and then matches **nothing**, failing every
row while looking like a data problem. Catching it at authoring time is the difference between a lint
error and an outage.

### 4.2 Nulls

**Value constraints apply only to non-null values.** `nullable` remains the sole null gate.

This mirrors the split `dtype_satisfies` already makes for R8 and keeps one question in one place: a
null in a nullable field is legal, and asking whether `None >= 1` is a category error. A null in a
*non*-nullable field already fails, as the `nullable` problem, before any constraint is consulted.

## 5. Compilation

### 5.1 JSON Schema

| Constraint | Keyword |
| --- | --- |
| `enum` | `enum` |
| `minimum` | `minimum` |
| `maximum` | `maximum` |
| `min_length` | `minLength` |

**The nullable-enum gotcha.** `minimum` and `minLength` apply only to instances of the type they
govern, so a `null` in a nullable field passes them without special handling. **`enum` is not
type-scoped** — it is a flat set of permitted instances. A nullable field carrying `enum: [0, 1]`
would therefore reject `null`, contradicting its own `nullable: true`.

So the compiler appends `None` to the enum when the field is nullable. Without it, `nullable` +
`enum` is silently broken in a way that looks like bad data.

### 5.2 Pandera

Each constraint compiles to a named `pa.Check` appended to the column's existing R8 family check:
`enum` → `isin`, `minimum` → `ge`, `maximum` → `le`, `min_length` → a length check that skips nulls
(per §4.2).

**Every check carries an explicit name** (`enum`, `minimum`, `maximum`, `min_length`). This is
load-bearing, not tidiness: `_validate_tabular` classifies failures by check name, and its `else`
branch labels anything unrecognized `retyped`. Unnamed value checks would report "sentiment is out of
range" as **a type change** — a wrong diagnosis pointing at the wrong upstream cause.

That classifier is §15 item 5c's known-fragile internals-parsing. This change adds to it rather than
fixing it; item 5c stays open and this is one more reason to do it.

### 5.3 Payload boundaries

`_validate_payload` branches on `required`, `type`, and `additionalProperties`. A `minimum` or `enum`
error from `jsonschema` matches **none** of them and is dropped on the floor — the loop simply does
not append a diff.

So payload boundaries need a new branch, or constraints compile into the JSON Schema and then do
nothing at runtime for `kind: payload`. A constraint that validates on one boundary kind and silently
no-ops on the other is worse than one that does not exist.

## 6. Runtime semantics

### 6.1 Severity

Value violations are **hard** diffs, joining `missing` / `retyped` / `nullable`. They flow through
the existing `observe` → `warn` → `enforce` ladder with no new knob: `enforce` raises, `warn` logs,
`observe` records.

Hard on **inputs and outputs alike**. Decision #2's open/complete asymmetry is about *extra fields*,
not about values. A vendor sending `sentiment: 1.4` is exactly incident-#1 shaped — it is the case
the system exists to catch.

### 6.2 Reporting

A new `FieldDiff.problem` variant, `"value"`. The model's *fields* are unchanged:

```
peec.prompts_export@1.0.0 at input 'prompts':
  value field 'sentiment' expected maximum=1.0,
  observed 3 of 10000 rows violate (e.g. 1.4, 2.7, 1.02)
```

Row-level failures need a count and exemplars where column-level failures need neither. Pandera's
`failure_cases` yields one row per offending value with its index, so both are available; samples cap
at three, because the fourth exemplar tells the reader nothing the third did not.

## 7. Public API and versioning

`FieldDiff` is on the frozen public surface (R9 §3.2). Adding a `problem` variant is a **deliberate
public-API change**:

- Version → **`0.2.0`**. Legitimate under 0.x, where a minor may break.
- `tests/test_public_api.py`'s frozen-surface test is updated *as part of the change*, which is the
  tripwire working as designed — a reviewed break, not a silent one.
- `CHANGELOG.md` gets the entry, and it must say plainly that a consumer matching exhaustively on
  `problem` will now see a value it has never seen.

## 8. Considered and rejected

| Option | Why not |
| --- | --- |
| Honor decision #1 literally — all value checks Python-side | Every repo re-authors the same range in code, and the JS SDK stays blind to constraints the schema knows. The principle's justification does not apply to keywords JSON Schema has. |
| Per-check severity (`on_violation: warn\|fail`) | A second severity axis beside the mode ladder. Two interacting knobs is how a kill switch becomes ambiguous — the `CONTRACT_DISABLED` lesson, one layer up. |
| Row-fraction threshold ("fail above 2%") | Adds a tuning constant with no principled value. "How did we choose 2%?" has no answer, and an unanswerable knob gets set to whatever silences the alert. |
| Value violations always `warn` | The failure this exists to fix *is* silence. The spec already notes (§5.2) that a non-blocking log line is the easiest thing in this system to ignore. |
| `pattern` / regex now | Not required by any of the four driving examples. Purely additive later, on the same mechanism. |
| Exclusive bounds (`exclusiveMinimum`) | Inclusive bounds express all four examples. Additive later. |
| The Python cross-field hook now | No caller. Its shape would be guessed, and it would be public surface. |
| `coerce=True` to normalize values | Never. It hides the drift criterion #1 exists to catch — the same reason R8 rejected it. |

## 9. Falsifiable criteria

Each constraint needs a **true positive and a true negative**. A check that always fires passes any
one-directional test, which is how a vacuous validator ships green.

1. **Per constraint, violation hard-fails** under `enforce`, naming the field, the constraint, the
   violating-row count, and sample values.
2. **Per constraint, conforming data passes.** The true negative.
3. **Nulls in a nullable field do not trip constraints** (§4.2).
4. **`nullable` + `enum` accepts `null`** — the §5.1 gotcha, which fails without the appended `None`.
5. **A value failure reports `problem="value"`,** not `"retyped"` — the §5.2 naming, which fails
   against an unnamed check.
6. **`minimum` on a `string` field fails at schema load,** not at validation time (§4.1).
7. **`enum` whose values mismatch the declared type fails at load** (§4.1).
8. **An enum violation on a `kind: payload` boundary raises** rather than vanishing (§5.3).
9. **The compiled JSON Schema carries the keywords** — the portability claim of §3, asserted rather
   than assumed.

## 10. Deliberately not built

- **Cross-field and custom-validator checks.** §15 item 4 remains open for exactly this.
- **`pattern`, exclusive bounds, `maxLength`, `multipleOf`.** Additive on this mechanism when a real
  case appears.
- **Fixing §15 item 5c** (classification by parsing library internals). §5.2 leans on it harder; it
  is not repaired here.
