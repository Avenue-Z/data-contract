# Value constraints — declarative, portable, at the boundary

**Status:** designed 2026-07-21, **revised three times after review (2026-07-21, 2026-07-22 ×2)**, unimplemented.
**Closes:** most of §15 item 4 (the value-check enrichment gap). Narrows what remains of it.
**Parent spec:** [2026-07-16-data-contract-system-design.md](2026-07-16-data-contract-system-design.md)
— read decision #1 (Portable Core), decision #2 (inputs open / outputs complete), §4.1, §5.2, §9.

> **Revision note.** The first draft's intent survived review; five of its mechanical claims did not.
> They are corrected here and marked *(rev.)* where the correction changes what an implementer does.
> The pattern in all five: the design asserted how a library or this codebase behaves without running
> it.
>
> **Revision 2** found two more of exactly that class, both in material revision 1 *added* — §5.4's
> ODCS mapping (read off the vendored schema's keyword list, never composed into a document and
> validated) and §5.2.1's drop rule (specified without checking what a value check does against a
> wrong dtype). Marked *(rev. 2)*. Revision 1 claimed "every behavioral claim below has now been
> executed" and that claim was itself unverified. Every table of results in this document is now
> pasted from a run.
>
> **Revision 3** closed the last one, and it was hiding behind a label rather than behind an
> unverified claim: §5.4 called ODCS's missing `nullable` "a pre-existing gap, not introduced here"
> and three rounds of review — including the ones that caught everything else — read past it. ODCS's
> `required` is documented as *null* semantics and this project emits its *presence* flag into it, so
> the gap was never "nullable is dropped"; it was "nullable's slot says the opposite." Marked
> *(rev. 3)*. The lesson is narrower than revisions 1–2's and worth keeping separate: **"pre-existing"
> is where an unexamined claim goes to be safe from review.**

## 1. The problem

`to_pandera` emits presence, type, and nullability. The runtime applies exactly that. So a boundary
today catches *structural* drift and nothing else: the pilot's likely real corruption — sentiment
outside `[-1, 1]`, `is_owned ∉ {0, 1}`, negative ranks, an empty `brand` — passes validation and
flows downstream.

That is the "silently misses the real bugs" half of the §15 gate. Structural drift is loud; nonsense
values are silent.

## 2. Scope

**Ships:** four declarative constraints — `enum`, `minimum`, `maximum`, `min_length` — authored on a
field, compiled to **all three** targets (Pandera, JSON Schema, ODCS), enforced through the existing
mode ladder. The three targets do not all express them the same way: in ODCS the bounds are
`logicalTypeOptions` while `enum` is a `quality` rule, because ODCS has no `enum` option and emitting
one *fails* `contract lint` (§5.4).

**Also ships, because the feature is incoherent without them:**

- An **aggregation step** in `_validate_tabular` (§5.2.1). The current per-row append plus last-wins
  de-dup cannot express "3 of 10000 rows" and silently discards diffs when a field violates more than
  one thing.
- A **`lint` fix** (§4.1.1). Today `lint` cannot see the authoring errors this design relies on it to
  catch.

**Deferred:** the Python-side hook for cross-field checks and custom validators. It has no caller
today. An extension point designed against hypothetical needs is shaped wrong, and this one would be
public surface. §15 item 4 stays open, narrowed to just that hook.

**Unchanged:** `coerce=False` and the R8 family check. Nothing here mutates data to make it pass.

## 3. Amendment to decision #1 (Portable Core) *(rev.)*

Decision #1 already lists **enums** in the portable structural core, in both places it states the
principle. The first draft claimed to be moving them; it was not. What actually moves is
`minimum` / `maximum` / `min_length`.

Decision #1 groups "ranges, regex, cross-column checks, custom validators" as non-portable on the
grounds that they cannot be pushed into a cross-language schema. That is true of the last two and
false of the first two: `minimum`, `maximum`, and `minLength` are standard JSON Schema 2020-12, Ajv
validates them, and ODCS v3.1.0 expresses them under `logicalTypeOptions` (§5.4).

The line as it should read:

- **Portable — part of the shared contract.** Presence, type, nullability, enums, and the numeric and
  length bounds a JSON Schema can express.
- **Not portable — Python-side local enrichment.** Cross-field and cross-column relationships, and
  custom validators. These cannot cross the language boundary. This is the principle's real content.

`pattern` belongs on the portable side of that line by the same argument. It is **not shipped here**
(§2), but *not* on the grounds that no driving example needs it — that argument does not survive
contact with the fourth example *(rev. 2)*. `min_length: 1` is a length floor, not a non-blank check:
verified, a two-space `brand` has length 2 and passes. So "empty `brand`" is only **partially**
covered, and closing it fully needs `pattern`. `pattern` is deferred on scope alone, and the residual
gap is recorded in §10 rather than argued away.

## 4. Authored format

Constraints are optional keys on a field. Every existing schema stays valid; this is additive at the
format level.

```yaml
# schemas/peec/prompts_export/2.0.0.yaml
schema: peec.prompts_export
version: 2.0.0
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

### 4.1 Applicability *(rev.)*

| Constraint | Valid on | Deferred for | Real reason |
| --- | --- | --- | --- |
| `minimum`, `maximum` | `int`, `float` | `date`, `datetime` | A date range is meaningful — it needs the cross-target encoding decision below, not a claim that it is meaningless. |
| `min_length` | `string` | — | — |
| `enum` | `string`, `int`, `bool` | `date`, `datetime`, `float` | **The targets disagree.** JSON Schema sees a date as an ISO string (`types.py`); pandas sees a `Timestamp`. Verified: `pd.Series([Timestamp("2026-01-01")]).isin(["2026-01-01"])` is `False`. A schema that passes one target and fails the other is worse than an unsupported feature. `float` is excluded because an enum over floats is exact equality. |

`enum` additionally requires a non-empty list whose values match the declared type. `enum: ["0", "1"]`
on an `int` field matches **nothing**, failing every row while looking like a data problem.

Supporting dates means first deciding a single wire encoding for constraint literals across all three
targets. That is a real design task, not an oversight, and it is deferred (§10).

**The third target disagrees too** *(rev. 2)*, which makes the deferral better-founded than the row
above states. In the vendored ODCS schema, `minimum` under the **`date`** branch is typed
`{"type": "string"}` while under the **`number`** branch it is `{"type": "number"}`. So a date bound
is an ISO string in JSON Schema, an ISO string in ODCS, and a `Timestamp` in pandas — three targets,
two encodings, and the conversion has to be decided rather than inferred.

#### 4.1.1 `lint` cannot catch these today — so this design fixes it *(rev.)*

The first draft said applicability errors "fail at `Schema.from_yaml`, so `contract lint` rejects
it." Both halves are wrong:

- `lint` resolves only schemas **referenced by the contract** it was given (`cli.py`). A new or
  not-yet-referenced schema file is never loaded, so a malformed constraint in it is never seen.
- `lint`'s `try/except` catches only `SchemaNotFound`. A pydantic `ValidationError` escapes as a raw
  traceback rather than the `LINT FAILED` report.

And in production the failure lands at **decoration time** — `_decorator` resolves the schema when
the decorator is applied, which is module import. An authoring typo therefore crashes at import: the
exact failure class R9 and §15 item 7 spent effort removing.

So this design includes a scoped `lint` change: walk and validate the schema files under the given
schema dirs, not only referenced ones, and catch `ValidationError` into the `LINT FAILED` report
alongside `SchemaNotFound`.

**Scope the walk to files the resolver would consider** *(rev. 2)* — stems that `_parse_semver`
parses. That helper returns `None` rather than raising *specifically* so the major-pin glob skips
strays like `latest.yaml` and `_template.yaml`, and its docstring says so. Linting every `*.yaml`
would turn a deliberate accommodation into a failure, making a template file a lint error. If
template files should be valid schemas, that is a separate decision and not one this design makes.

Residual, stated rather than hidden: `lint` in CI is the control. A repo that skips `lint` still gets
an import-time crash from a malformed constraint. Making resolution lazy is a larger change and is
out of scope here.

### 4.2 Nulls *(rev.)*

**Value constraints apply only to non-null values.** `nullable` remains the sole null gate — the same
split `dtype_satisfies` makes for R8.

This works because `pa.Check(...)` defaults `ignore_na=True`. Verified. **Every check this design
emits sets `ignore_na=True` explicitly anyway.** A guarantee the spec makes to consumers should not
rest on an unstated default of a pinned dependency that a bump could change; writing it costs
nothing.

### 4.3 Rollout and versioning — adding a constraint is a **major** bump *(rev.)*

The first draft claimed a consumer "pinned to `1.0.0` is unaffected… this change cannot break a
running system by itself." That is false under this project's own recommended pinning:

- The parent spec's strategy is **major-pin plus lockfile** (`@1`); `tests/fixtures/contract.yaml`
  pins `@1`.
- `Resolver` resolves `@1` to the **highest matching minor** — `max(candidates)`.
- **There is no lockfile implementation anywhere in the repo.** It is designed (§9) and unbuilt.

So publishing `1.1.0` with `minimum: -1.0` would hard-fail a running consumer on its next resolve,
with no action on its part. The reassurance was written against a pinning mode nobody was told to
use.

**Policy: adding, tightening, or removing a value constraint is a breaking schema change and requires
a major version bump.** A constraint can fail data that previously passed, which is the definition of
breaking. §9 already makes major the staged-migration mechanism — "consumers adopt a new major on
their own timeline" — and under `@1` pinning a major bump genuinely does leave existing consumers
untouched, which is what the first draft wrongly claimed for a minor.

**This is policy, not machinery, until Phase 2.** The CI check that fails a mis-declared bump is
Phase 2 (§9) and does not exist. Until it does, nothing mechanically stops someone publishing
constraints in a minor and breaking every `@1` consumer at once. Say so in the authoring skill
(§5.5).

**Per-boundary rollout.** A schema author cannot know every consumer's data. The intended sequence
for adopting a constraint-bearing major is the mode ladder that already exists: move the pin with the
boundary in `observe`, read the event log, then promote to `enforce`. This is also the answer to the
severity objection in §8 — the ladder is per-boundary, so a consumer soaks value constraints without
weakening structural enforcement anywhere else.

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

### 5.2 Pandera — the classifier keys on `error=`, not `name=` *(rev.)*

Each constraint compiles to a `pa.Check` appended to the column's existing R8 family check:
`enum` → `isin`, `minimum` → `ge`, `maximum` → `le`, `min_length` → a length check, all with
`ignore_na=True` (§4.2).

The first draft said each check must carry an explicit **`name=`**, and called it load-bearing. It is
load-bearing and `name=` does not deliver it. Verified against pandera 0.32.1: the `check` column of
`failure_cases` is populated from **`check.error`**, falling back to the check's rendered form.

```
pa.Check.isin([0, 1], name="enum")                  ->  check == "isin([0, 1])"
pa.Check(fn, name="minimum", error="minimum")       ->  check == "minimum"
```

`name=` does surface for a bare `pa.Check(fn, name=...)`, but not for the built-in constructors this
design uses. **So every check sets `error="<constraint>"`.** Implemented with `name=`, every value
violation falls through to the `else` at `runtime.py` and is reported as `retyped` — the precise
misdiagnosis this section exists to prevent.

This is already observable in shipped code: `_family_check` sets both a `name=` and a prose `error=`,
and the prose is what reaches the classifier — which is why dtype failures land in the `else` today.
They are labelled `retyped`, which happens to be correct for a dtype failure, so nothing looked
broken.

**This makes §15 item 5c worse, and that should be said out loud.** Control flow is now keyed on a
string slot that pandera fills from an error-*message* field, under a pinned dependency, with no
compile-time guarantee. A pandera bump that changes how `failure_cases` is populated silently
re-labels every value violation. Item 5c stays open and this design raises its priority; a proper fix
carries checks' identity out-of-band rather than parsing it back out.

#### 5.2.1 Aggregation — the current loop cannot produce §6.2 *(rev.)*

`_validate_tabular` appends **one `FieldDiff` per failure-case row**, then de-dups per field with
`seen[d.field] = d` — **last wins**. Two consequences the first draft missed:

1. "3 of 10000 rows violate" cannot come out of that loop at all. It needs a **group-by
   `(field, check)`** that the draft never mentioned.
2. Last-wins **discards diffs**. A field violating both `minimum` and `maximum`, or violating a value
   check *and* the dtype family check, reports one arbitrary problem chosen by pandera's frame
   ordering. Confirmed in review: with the dtype row sorted after the value row, the value diff is
   the one thrown away.

So this design replaces the de-dup with aggregation. **The order of these steps is part of the
spec** — see §5.2.2:

1. **Extract the field name**, then **apply the dtype-drop rule** (§5.2.2).
2. **Group** the surviving failure cases by `(field, check)`; emit **one** `FieldDiff` per group,
   carrying the row count and up to three sample values.
3. **Structural diffs keep collapsing per field** — "column missing" twice is noise. **Value diffs do
   not collapse across different constraints**, because `minimum` and `maximum` on one field are two
   distinct facts an operator needs.

**Group on the resolved field name, not the raw frame column.** For `column_in_dataframe` the field
name lives in `failure_case` and `column` is `NaN`; the existing loop already handles that split.
Keying the group-by on the raw `column` would put every missing column in one `NaN` bucket.

#### 5.2.2 The dtype-drop rule is mandatory, and needs a fourth edit site *(rev. 2)*

When a field has both a dtype-family failure and a value failure, the **dtype diff wins and the value
diffs are dropped**. Revision 1 called this a tidiness rule. It is not — it is required for
correctness, and the reason is worse than "noise".

A value check on a wrong-typed column does not return `False`; it **raises**, and pandera captures
the exception as the failure case. Executed, declaring `float` and passing strings:

```
check='column dtype does not satisfy...'   failure_case='False'
check='minimum'   failure_case='TypeError("\'>=\' not supported between instances of ...")'
check='maximum'   failure_case='TypeError("\'<=\' not supported between instances of ...")'
```

Without the drop rule a `ContractViolation` reports `violating_rows: 1` and
`samples: ["TypeError(\"'>=' not supported between instances of 'str' and 'float'\")"]` — a Python
exception repr presented to an operator as a sample of their data.

**This is why the rule must run before aggregation** (§5.2.1 step 1): grouping first computes counts
and samples off `TypeError` reprs, then discards them, which is the same wasted-and-wrong work in a
different order.

**And it requires a fourth edit site.** Implementing "did the dtype check fail for this field?" means
recognizing the family check's row, and `_family_check` currently sets `error=` to a prose sentence.
§5.2 mandates `error="<constraint>"` for the four new checks; **`_family_check` must be changed to a
machine-recognizable `error="dtype_family:<type>"` too.** Without it, §5.2.1 and criterion 7 are
unbuildable. This is safe: the prose currently reaches only pandera's own exception text, while
`ContractViolation` renders its own message.

### 5.3 Payload boundaries — the branch is built *(rev.)*

`_validate_payload` branches on `required`, `type`, and `additionalProperties`. A `minimum` or `enum`
error from `jsonschema` matches none of them and is dropped on the floor.

The first draft stated this fork and never picked a side, then wrote a test criterion assuming one.
**Decision: build the branch.** Constraints compile into the JSON Schema for `kind: payload`, and
`_validate_payload` gains a branch mapping `enum` / `minimum` / `maximum` / `minLength` validator
errors to a `value` diff.

Payload errors are per-document, not per-row, so `violating_rows` is `None` there and the sample is
the offending value. A constraint that enforces on tabular boundaries and silently no-ops on payload
ones is worse than one that does not exist.

### 5.4 ODCS — the third target, and `enum` does not go where the bounds go *(rev. 2)*

`compile/odcs.py` exists and `contract lint` compiles to ODCS and validates it **unconditionally**,
so ODCS is a real target the first draft never mentioned. `_schema_block` emits `name` /
`logicalType` / `required` only — it drops `nullable` today, and would drop every constraint.

That matters more than the other two: the ODCS document is the artifact that actually **leaves the
Python process**. §3 cannot claim portability while the exported artifact carries none of it.

**`logicalTypeOptions` is not a free-form bag.** Revision 1 read the keyword list off the vendored
schema and never composed a document. It is type-scoped through an `allOf` / `if`-`then` chain keyed
on `logicalType`, and every typed branch sets `additionalProperties: false`. Executed against
`validate_odcs`:

| Emitted | Result |
| --- | --- |
| `number` + `minimum`/`maximum` | OK |
| `integer` + `minimum` | OK |
| `string` + `minLength` | OK |
| **`enum` on string / integer / number** | **FAIL** — `Additional properties are not allowed ('enum' was unexpected)` |
| `enum` on **boolean** | "OK" — **vacuously**, see below |

So emitting `enum` into `logicalTypeOptions` would not degrade the export; it would make
`contract lint` **fail** on the very example that motivated this design (`is_owned ∈ {0, 1}`).

**The boolean pass is the dangerous result, not the reassuring one.** There is no `boolean` branch in
the chain, so no `if` fires and `logicalTypeOptions` falls back to its bare definition,
`{"type": "object"}`. Verified: `{"totally_made_up": "anything"}` on a boolean field also validates.
`_ODCS_LOGICAL` maps `bool → "boolean"`, and §4.1 permits `enum` on `bool`, so that path would emit
unvalidated content no ODCS consumer has a rule for, under a green test.

**Rule: never emit `logicalTypeOptions` for a `logicalType` with no branch in the chain.** A
key that validates because nothing checked it is worse than one that fails.

#### 5.4.1 The mapping, as verified

- **`minimum` / `maximum` / `min_length` → `logicalTypeOptions`** on `number` / `integer` / `string`.
- **`enum` → a `quality` rule**, which is ODCS's actual home for an allowed-value set:

```json
{"type": "library", "metric": "invalidValues",
 "arguments": {"validValues": [0, 1]}, "mustBe": 0}
```

Read as "the count of values outside `validValues` must be zero" — the enum semantic. `metric` is
required by `DataQualityLibrary`, and the operator comes from the `oneOf` in `DataQualityOperators`,
so `mustBe: 0` is load-bearing and not decoration; omitting it fails validation.

A complete four-constraint document in this shape was composed and passed `validate_odcs`. That
end-to-end check — not a keyword grep — is what criterion 14 now asserts.

**Implementation note, not a design point.** A malformed quality rule reports
`Unevaluated properties are not allowed ('arguments', 'metric' were unexpected)` — the
`unevaluatedProperties` construct blames the keys that are *correct* rather than the one that is
missing or wrong. The compiler emits the shape, so no author can hit this; whoever builds §5.4.1
will, and would otherwise lose time chasing `metric` when the real fault is elsewhere in the rule.

#### 5.4.2 Nulls in the ODCS export — the gap is not what revisions 1–2 called it *(rev. 3)*

Both earlier revisions disposed of this in one line: "ODCS's `nullable` omission is a pre-existing
gap, not introduced here." Nobody checked what ODCS's `required` means. From the vendored schema:

```json
"required": {"type": "boolean", "default": false,
             "description": "Indicates if the element may contain Null values;
                             possible values are true and false. Default is false."}
```

**ODCS `required` is null semantics, not presence semantics, and there is no `nullable` key on the
property** — verified against the full property list. `_schema_block` emits `"required": f.required`,
this project's *presence* flag, into it.

So `nullable` is not merely dropped: **the slot it belongs in is already occupied by a different
concept.** A field that is `required: true, nullable: true` exports an ODCS property asserting the
opposite of what the schema says about nulls. Before this design that lost information. This design
adds bounds and allowed-value rules whose correctness depends on the null story, which turns a lossy
export into one where an emitted rule means something the contract does not.

That is exactly the failure §5.1 spends effort preventing for JSON Schema. Exempting ODCS from a rule
the document applies everywhere else is not a scope decision, it is an unexamined one — and
"pre-existing" is where such claims go to be safe from review.

**The fix, all four parts verified against `validate_odcs`:**

1. **Stop emitting presence into ODCS `required`.** The slot is documented as a null flag; putting a
   presence flag there asserts something we do not mean, whichever polarity is intended.
2. **`nullable: false` → a quality rule** `{"type": "library", "metric": "nullValues", "mustBe": 0}`.
   `nullValues` is in `DataQualityLibrary`'s `metric` enum, so this says "zero nulls" unambiguously,
   which the `required` boolean does not.
3. **A nullable field carrying `enum` appends `null` to `validValues`** —
   `{"validValues": [0, 1, null]}` — the direct analogue of §5.1's appended `None`, for the same
   reason. ODCS lists `nullValues` and `invalidValues` as *separate* metrics, so whether
   `invalidValues` counts nulls is engine-defined; appending makes it not matter.
4. **Presence is not exported**, and that is stated rather than implied. There is no unambiguous ODCS
   slot for it. `missingValues` is a candidate metric, but its semantics against `nullValues` are
   engine-defined, and an absent claim is better than a wrong one.

**A note for whoever implements part 1.** The vendored description reads "*may contain* Null values"
with `default: false`, which is the opposite polarity from the conventional reading of a `required`
flag. That ambiguity is a second, independent reason not to emit into it: the design cannot establish
the intended polarity from the schema text, and a boolean emitted with a guessed polarity is worse
than a quality rule that says what it means.

No existing test asserts on ODCS `required`, so parts 1–2 change output that nothing currently pins.

## 6. Runtime semantics

### 6.1 Severity

Value violations are **hard** diffs, joining `missing` / `retyped` / `nullable`. They flow through
the existing `observe` → `warn` → `enforce` ladder with no new knob.

Hard on **inputs and outputs alike**. Decision #2's open/complete asymmetry is about *extra fields*,
not values. A vendor sending `sentiment: 1.4` is exactly incident-#1 shaped.

The operational consequence is owned in §4.3 and §8, not waved away: one bad row in ten thousand
stops the batch as hard as a vanished column, and the rollout answer is to adopt a
constraint-bearing major with the boundary in `observe` first.

### 6.2 Reporting — typed fields, not prose *(rev.)*

The first draft put `"maximum=1.0"` in `expected` and `"3 of 10000 rows violate (e.g. 1.4, …)"` in
`observed`. That silently repurposes two fields whose current meanings are asserted by
`test_public_api.py`, and it forces a consumer to regex prose to recover a number — from the very
type `FieldDiff` exists to spare them.

The four existing fields keep their meanings. Three optional fields carry the value story:

```python
class FieldDiff(BaseModel):
    field: str
    expected: str                    # unchanged: the declared type
    observed: str                    # unchanged: the observed dtype / state
    problem: Literal["missing", "retyped", "nullable", "extra", "value"]
    constraint: str | None = None    # "maximum=1.0", "enum=[0, 1]"
    violating_rows: int | None = None
    samples: list[str] = []
```

`None` / `[]` on every structural diff. Rendered:

```
peec.prompts_export@2.0.0 at input 'prompts':
  value field 'sentiment' violates maximum=1.0
  — 3 of 10000 rows (e.g. 1.4, 2.7, 1.02)
```

Samples cap at three. They are drawn from production data, so the authoring skill should note that a
constrained field holding sensitive values will have examples surface in logs and exception messages.

## 7. Public API, versioning, and the four edit sites *(rev. 2)*

`FieldDiff` is on the frozen public surface (R9 §3.2). This is a deliberate public change:

- Version → **`0.2.0`**. Legitimate under 0.x.
- `tests/test_public_api.py`'s frozen-surface test is updated **as part of the change** — the
  tripwire working as designed, a reviewed break rather than a silent one.
- `CHANGELOG.md` must say two things, not one: a consumer matching exhaustively on `problem` will see
  a value it has never seen, **and** `FieldDiff` has gained three fields.

**`problem` is declared in two places and gated in a third, and a fourth site is required by
§5.2.2.** All four must change together:

| Site | What |
| --- | --- |
| `runtime.py` | `Problem = Literal[...]` |
| `errors.py` | `FieldDiff.problem: Literal[...]` |
| `runtime.py` | `hard = [d for d in diffs if d.problem in (...)]` — a hardcoded tuple |
| `compile/pandera_compile.py` | `_family_check`'s `error=` → `"dtype_family:<type>"`, so the drop rule can recognize it (§5.2.2) |

The duplication is pre-existing. Adding a fifth variant makes a divergence between the two `Literal`s
possible for the first time in a way mypy will not necessarily catch at the append site. Collapsing
them to one definition is a small, in-scope cleanup and this design does it.

## 8. Considered and rejected

| Option | Why not |
| --- | --- |
| Honor decision #1 literally — all value checks Python-side | Every repo re-authors the same range in code, and the JS SDK and ODCS export stay blind to constraints the schema knows. The justification does not apply to keywords JSON Schema and ODCS both have. |
| Per-check severity (`on_violation: warn\|fail`) | A second severity axis beside the mode ladder. Two interacting knobs is how a kill switch becomes ambiguous — the `CONTRACT_DISABLED` lesson one layer up. **The cost is real:** `mode` is per-boundary, so "structural enforce + value warn" on one boundary is unavailable. §4.3's observe-then-promote rollout is the answer, and it is weaker than per-check severity would have been. Accepted knowingly. |
| Row-fraction threshold ("fail above 2%") | A tuning constant with no principled value. An unanswerable knob gets set to whatever silences the alert. |
| Value violations always `warn` | The failure this exists to fix *is* silence. §5.2 of the parent spec already notes a non-blocking log line is the easiest thing here to ignore. |
| Prose count/samples in `observed` | Finding 6. Breaks the field's asserted meaning and makes consumers regex a number out of a sentence. |
| `name=` on pandera checks | Verified not to reach the classifier for the built-in constructors. §5.2. |
| Publishing constraints in a **minor** schema bump | Finding 4. `@1` + `max(candidates)` + no lockfile means it breaks running consumers on their next resolve. |
| Declaring the ODCS export structural-only | ODCS v3.1.0 expresses these under `logicalTypeOptions` **and `quality` rules** — the bounds in the former, `enum` and null-tolerance in the latter (§5.4.1, §5.4.2). The exclusion would be a choice to make §3 false for the exported artifact. |
| `pattern` / regex now | Portable (§3); deferred on **scope**, not on "no driving example needs it" — §3 retracts that argument, since `min_length: 1` accepts `"  "` and leaves the "empty `brand`" example partially open. Additive later on the same mechanism. |
| Exclusive bounds (`exclusiveMinimum`) | Inclusive bounds express all four examples. Additive later. |
| The Python cross-field hook now | No caller. Its shape would be guessed, and it would be public surface. |
| `coerce=True` to normalize values | Never. It hides the drift criterion #1 exists to catch — R8's reason. |

## 9. Falsifiable criteria *(rev.)*

Each constraint needs a **true positive and a true negative**. A check that always fires passes any
one-directional test, which is how a vacuous validator ships green.

1. **Per constraint, violation hard-fails** under `enforce`, naming field, constraint, row count, and
   samples.
2. **Per constraint, conforming data passes.** The true negative.
3. **Nulls in a nullable field do not trip constraints** (§4.2).
4. **`nullable` + `enum` accepts `null`** — fails without the appended `None` (§5.1).
5. **A value failure reports `problem="value"`, not `"retyped"`** — fails if the check is built with
   `name=` instead of `error=` (§5.2). *This test is the guard on the whole classification story.*
6. **A field violating two constraints at once reports both diffs** — fails against the current
   last-wins de-dup (§5.2.1).
7. **A field failing both its dtype check and a value check reports the dtype diff only**, by the
   documented rule and not by frame ordering (§5.2.1).
8. **`violating_rows` and `samples` are populated and typed** — an integer, not a substring of prose
   (§6.2).
9. **`minimum` on a `string` field fails at schema load** (§4.1).
10. **`enum` whose values mismatch the declared type fails at load** (§4.1).
11. **`lint` reports a malformed constraint as `LINT FAILED`**, in an unreferenced schema file, and
    does not raise a traceback (§4.1.1).
12. **An enum violation on a `kind: payload` boundary raises** rather than vanishing (§5.3).
13. **The compiled JSON Schema carries the keywords** (§3/§5.1).
14. **The compiled ODCS document validates against the vendored v3.1.0 schema for a source schema
    carrying all four constraints — `enum` included.** *(rev. 2)* The enum-bearing field is the point:
    without it this criterion passes while the case that breaks `contract lint` is never exercised.
15. **`enum` compiles to a `quality` rule, not to `logicalTypeOptions`** — asserted directly, because
    emitting it as a `logicalTypeOption` fails validation on string/integer/number and passes
    *vacuously* on boolean (§5.4).
16. **[Regression guard, not a discriminating criterion]** *(rev. 3)* **No `logicalTypeOptions` key is
    emitted for a `logicalType` with no branch in the ODCS chain** (§5.4). Labelled honestly: given
    §5.4.1 routes `enum` to `quality` and §4.1 confines the bounds to types that all have branches,
    **no authorable schema can reach the state this checks**. It cannot fail today. It is kept to
    catch a future re-route of `enum` back into `logicalTypeOptions`, where it would pass vacuously
    on `boolean` — but §9's preamble promises each criterion discriminates, so this exception is
    marked rather than left to look like the others.
17. **A wrong-typed column reports the dtype diff with no `TypeError` text in `samples`** (§5.2.2) —
    the observable form of criterion 7, and what fails if the drop rule runs after aggregation.
18. **A `nullable` field's ODCS export carries no assertion contradicting `nullable`** *(rev. 3)* —
    specifically, no `required` flag standing in for presence (§5.4.2). This is the ODCS analogue of
    criterion 4, and the gap two revisions dismissed as "pre-existing".
19. **`nullable: false` emits a `nullValues` quality rule with `mustBe: 0`** (§5.4.2).
20. **A nullable field carrying `enum` emits `validValues` including `null`** (§5.4.2) — fails
    without it, and the failure is invisible in-process: only a third-party ODCS consumer would
    enforce over nulls what §4.2 exempts.

## 10. Deliberately not built

- **Cross-field and custom-validator checks.** §15 item 4 remains open for exactly this.
- **Constraints on `date` / `datetime`.** Needs one wire encoding for constraint literals agreed
  across Pandera, JSON Schema, and ODCS first (§4.1).
- **`enum` on `float`.** Exact float equality.
- **Presence in the ODCS export.** No unambiguous slot exists (§5.4.2); `missingValues` is a
  candidate metric whose semantics against `nullValues` are engine-defined.
- **`pattern`, exclusive bounds, `maxLength`, `multipleOf`.** Additive when a real case appears.
  **Known residual:** without `pattern`, the "empty `brand`" driving example is only partially
  covered — `min_length: 1` rejects `""` but accepts `"  "` (verified). A whitespace-only brand is
  the same bug as an empty one and still passes (§3).
- **Fixing §15 item 5c** (classification by parsing library internals). §5.2 leans on it harder and
  raises its priority; it is not repaired here.
- **ODCS `nullable`.** Pre-existing gap (§5.4).
- **Lazy schema resolution.** Would remove the residual import-time crash in §4.1.1.
