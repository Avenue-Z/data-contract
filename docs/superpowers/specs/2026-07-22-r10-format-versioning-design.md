# Versioning the authored format — strict keys first, `format_version` second

**Status:** designed 2026-07-22, **revised three times after review (2026-07-22 ×3)**, unimplemented.
**Closes:** R10, with a stated residual (§6). Does not close it silently.
**Parent spec:** [2026-07-16-data-contract-system-design.md](2026-07-16-data-contract-system-design.md)
— read R10 in §14, §15 item 3, decision #1 (Portable Core), and R6.
**Sibling:** [2026-07-21-value-constraints-design.md](2026-07-21-value-constraints-design.md) §4.3,
whose major-schema-bump convention is the only thing standing in for this design today.

> **On evidence.** Every behavioral claim here was executed against this repo at `0.2.0`
> (pydantic 2.13.4) before it was written down. Runs are pasted, not paraphrased. Where something
> was *not* run, it says so — and §5.2 is the section to read first, because it is the one place
> where the design's most user-visible output is specified rather than observed.
>
> Three review rounds and what each caught are in
> [`docs/notes/2026-07-22-r10-review-log.md`](../../notes/2026-07-22-r10-review-log.md). Sections
> changed by review carry *(rev. N)*. The log is not needed to implement this document.

## 1. The problem

R10 says the authored format carries no format-version, so a `contract-core` format change breaks
every repo's authored files with no migration. That framing is right about the risk and wrong about
the mechanism, and the difference decides what gets built.

The mechanism is not a version mismatch. It is that **every model in the authored format silently
discards keys it does not recognise.** `Schema`, `Field`, `Contract`, and `BoundarySpec` are plain
pydantic `BaseModel`s, so `extra` defaults to `"ignore"`.

This is not hypothetical, and it is not in the future. `0.2.0` added four keys to a field — `enum`,
`minimum`, `maximum`, `min_length`. A reader from `0.1.0` does not have them. Run against the real
fixture, with a `Field` model reconstructed as `0.1.0` defined it:

```
=== v0.1.0 reader on a v0.2.0-authored schema (tests/fixtures/schemas/peec/prompts_export/2.0.0.yaml) ===
   {'name': 'prompt',    'type': 'string', 'required': True, 'nullable': False}
   {'name': 'sentiment', 'type': 'float',  'required': True, 'nullable': True}
   {'name': 'position',  'type': 'int',    'required': True, 'nullable': True}
   {'name': 'is_owned',  'type': 'int',    'required': True, 'nullable': True}
  -> parsed CLEAN; every constraint dropped
```

`min_length: 1` on `prompt`, `[-1.0, 1.0]` on `sentiment`, `minimum: 1` on `position`, `enum: [0, 1]`
on `is_owned` — all four gone, no error, no warning. The boundary still validates. It validates a
**weaker form** than the file it just read, and it reports success.

That is the failure this design exists to stop, and it is worse than the one R10 describes. A format
change that *breaks* a repo is loud, and loud is survivable. A format change that quietly narrows
what a validator checks is a drift detector reporting all-clear on data it was authored to reject.
It is R6's weaker-form gap — the one decision #1 confines to the Python/JS boundary — reappearing
**inside a single language, between two versions of the same library.**

## 2. Scope

**Ships two controls and one error type:**

- **Control A — strict keys** (§3). `extra="forbid"` on the four authored-format models. Turns a
  silent drop into a loud refusal. This is what closes §1.
- **Control B — `format_version`** (§4). An optional major-only format stamp with a supported set.
  Covers the one class Control A structurally cannot see: an existing key whose *meaning* changed.
- **`ContractFormatError`** (§5). One exported exception at the `from_yaml` boundary, carrying a
  message that names the cause instead of pydantic's generic wording.

**Ordering is load-bearing.** Control A ships first and would be worth shipping alone; Control B is
worth little without it. §8 records why.

**Deliberately out of scope:** `source` / `sink` and the `json_schema` payload body (§7).

**Unchanged:** every existing authored file, every compile target, the mode ladder, `coerce=False`,
the R8 family check, and the value-constraints spec's §4.3 major-schema-bump convention, which
remains the mitigation for the residual in §6.

## 3. Control A — strict keys

```python
model_config = ConfigDict(extra="forbid")
```

on `Schema` ([schema.py](../../../src/contract_core/schema.py)), `Field`
([types.py](../../../src/contract_core/types.py)), and `Contract` + `BoundarySpec`
([contract.py](../../../src/contract_core/contract.py)).

### 3.1 Blast radius — measured here, unmeasured downstream *(rev. 3)*

The four edits were applied and the full suite run:

```
186 passed, 2 warnings in 3.45s
```

**Zero failures.** The two warnings are the pre-existing `schema`-shadows-`BaseModel` notices,
unrelated to this change.

**What this run does and does not prove *(rev. 3).*** It proves that nothing *in this repo* — no
fixture, no test, no authored file — carries an undeclared key. It does **not** prove that adoption
is free, because **every authored file that matters lives in a consuming repo**, which is where R10
was filed in the first place. This run samples the wrong population for that claim, and an earlier
draft made it anyway ("it costs nothing to adopt") in a document whose thesis is that unsampled
claims are the defect.

Stated correctly: **Control A is a breaking change for any consumer whose authored files carry a
stray key** — a typo, a hand-added annotation, a key from a newer `contract-core`. That is
intentional, and it is the entire point: those files are currently being read with the stray key
silently dropped. But it is a break, it belongs in the `0.3.0` CHANGELOG in those words (§11), and
the cost of adoption is unknown until a consuming repo runs it.

What the run *does* support is the ordering argument: Control A requires no changes to this repo's
own artifacts, so nothing about shipping it first is blocked on a migration here.

### 3.2 What it catches

pydantic reports **every** extra key across **all** nesting levels in a single error — verified:

```
Outer.model_validate({"fields": [{"name": "s", "future_a": 1, "future_b": 2}], "future_top": 3})
  -> error count: 3
       fields.0.future_a
       fields.0.future_b
       future_top
```

So the diagnostic is complete on the first run: an operator sees the full set of keys their reader
does not understand, not the first one. Two classes are caught:

1. **Version skew** — a file authored against a newer `contract-core`. This is §1.
2. **Authoring typos** — `requird: true` today parses clean and silently defaults `required` to
   `True`. Under strict keys:

   ```
   1 validation error for Schema
   fields.0.requird
     Extra inputs are not permitted [type=extra_forbidden, input_value=True, input_type=bool]
   ```

   A typo'd constraint is exactly the "constraint that looks declared but is not" class the parent
   spec's §4.1 satisfiability checks were built to reject. Strict keys close the spelling half of it.

### 3.3 What it cannot catch

An **existing key whose meaning changed**. If `nullable` were ever redefined, or `minimum` became
exclusive rather than inclusive, the key is still known, still parses, and still silently means
something the author did not write. No key-set check can see this. That is what Control B is for,
and it is the only thing Control B is for.

## 4. Control B — `format_version`

An optional top-level key on `Schema` and `Contract` — **not** on `Field` or `BoundarySpec`, which
version with the file that contains them.

```yaml
format_version: v1
schema: peec.prompts_export
version: 2.0.0
kind: tabular
fields:
  - name: sentiment
    type: float
    minimum: -1.0
    maximum: 1.0
```

- **Two constants, not one** — `READABLE_FORMAT_VERSIONS` and `CURRENT_FORMAT_VERSION` (§4.5). Both
  are `"v1"` today; they are separate because they answer different questions and diverge the moment
  `v2` exists.
- **A missing key means `v1`**, because a missing stamp can only mean "authored before stamps
  existed" — which *is* `v1`. This default lives in the `from_yaml` dispatcher, **not** in the model
  field (§4.5). No existing file breaks, and none needs editing.
- **Both constants live in `types.py`** and are imported by `schema.py` and `contract.py` — one
  definition each, for the reason `errors.py` gives for `Problem`: two copies of the same constant
  can drift, and a `Schema` and a `Contract` disagreeing about which format versions exist is
  precisely the mis-parse this control prevents. `types.py` imports neither module, so there is no
  cycle.
- **Major-only.** `v1`, `v2` — no minor component. §8 records why semver loses here.
- **Refusal is total.** A reader that does not fully understand a file does not partially accept it.
  Partial acceptance of a schema file is precisely the weaker-form validation of §1.

### 4.1 When `format_version` bumps

**Only on a semantic change** — an existing key whose meaning changed (§3.3). Additive changes do
**not** bump it, because Control A already makes those loud. Under this policy `v1` should be
expected to last a long time, and that is the intended outcome, not a sign the control is unused:
Control B is a fire escape, and a fire escape that is never used is working.

This is the load-bearing difference from the R10 risk row, which implies a version stamp is the
primary control. It is the secondary one. §8 records the version-stamp-only alternative.

What happens *when* it bumps — how a reader accepts two versions at once — is §4.4. That is the half
of Control B that actually gets exercised, and specifying only the refusal would leave the control
half-designed.

### 4.2 Interaction with Control A

The two compose without special-casing. `format_version` becomes a declared field, so it passes
strict keys; an unsupported *value* is rejected by the validator, not by the extra-key rule.
Verified: with strict keys applied and `format_version` **not yet declared**, `format_version: v2`
is rejected as `extra_forbidden` — correct behavior, and the reason both controls must ship in the
**same** release rather than across two.

### 4.3 Why the key is `format_version` and not `apiVersion` *(rev.)*

The first draft of this design called the key `apiVersion`, following the R10 risk row. Review caught
it. Two independent reasons, both verified:

**1. `apiVersion` is already taken, in this codebase, on the same object.**
[`odcs.py:84`](../../../src/contract_core/compile/odcs.py#L84) emits `"apiVersion": "v3.1.0"` into
the ODCS document, where it means *the version of the ODCS standard*. `to_odcs` takes a `Contract`
and emits an `apiVersion` — so a `Contract.apiVersion` meaning *our authored-format version* would
put two unrelated meanings behind one name, one function apart, with the wrong wiring
(`"apiVersion": contract.apiVersion`) looking entirely natural.

The severity is bounded, and the spec should say so rather than overstate it. `to_odcs` builds its
dict key by key and never `model_dump()`s a model, so nothing propagates by accident today. And the
vendored ODCS schema constrains `apiVersion` to an **enum** — verified:

```
"apiVersion": {"type": "string", "default": "v3.1.0",
               "enum": ["v3.1.0", "v3.0.2", "v3.0.1", "v3.0.0", "v2.2.2", "v2.2.1", "v2.2.0"]}
```

`v1` is not in it, so the wrong wiring fails `validate_odcs` loudly rather than shipping a corrupt
document. This is a **maintainability** hazard, not a latent correctness bug — but it is free to
avoid.

**2. `apiVersion` would be the only camelCase key in the format.** Every key across all four models,
verified:

```
Schema         ['schema', 'version', 'kind', 'fields', 'json_schema']
Contract       ['system', 'version', 'raw', 'inputs', 'outputs']
BoundarySpec   ['name', 'schema', 'mode', 'source', 'sink']
Field          ['name', 'type', 'required', 'nullable', 'enum', 'minimum', 'maximum', 'min_length']
```

Eighteen keys, all lowercase or snake_case. `apiVersion` is casing borrowed from ODCS and Kubernetes
that this format never adopted. **This is the stronger of the two reasons** — it would hold even if
`odcs.py` did not exist, because a format that is snake_case in eighteen places and camelCase in the
nineteenth teaches authors nothing except that the rule is unreliable.

`format_version` sits next to the existing `version` key without ambiguity: `version: 2.0.0` is the
*schema's* semver, `format_version: v1` is the *format's*, and the `v` prefix keeps them visually
distinct. The `format` key that appears inside `source`/`sink` (`{kind: file, format: csv}`) is at a
different nesting level, in a dict nothing reads (§7).

`format_version` is **not** exported to ODCS. The ODCS document has its own `apiVersion` for the ODCS
standard; how *this* project versions its authored files is an authoring-side concern with no slot in
a published data contract.

### 4.4 The accept path — normalize on read, do not branch on use *(rev. 2)*

"Refusal is total" fully specifies how a reader *rejects* a version. Review caught that the design
never said how a reader *accepts two* — which is the only path Control B will ever actually run,
since the refusal path exists to be rare.

**A reader reads every version it understands: `READABLE_FORMAT_VERSIONS = {"v1", "v2"}`, not
`{"v2"}`.** Narrowing to the newest version alone would break every file in production
simultaneously, which is the loud total break §1 calls survivable but which nobody would have planned
for. The readable set is additive.

**The upcast happens on the raw dict, in `from_yaml`, before `model_validate`.** A tiny step reads
`format_version` off the parsed YAML, applies one function per version step (`_v1_to_v2`) — including
rewriting the key to `CURRENT_FORMAT_VERSION` — and hands the current-format dict to the model.
**The models only ever implement the newest format**, and therefore accept only
`CURRENT_FORMAT_VERSION`. §4.5 is why that is two constants rather than one; reading §4.4 alone
leaves a contradiction that two revisions of this document did not see.

This is where the design differs from the obvious reading of "support two versions." The alternative
— keep both meanings live in the model and branch at the changed key — is worse in a way that
compounds:

- `Field` does not know which file it came from, so a version-conditional `nullable` would have to be
  threaded down from `Schema` into every field, and from there into all three compile targets.
- Version conditionals inside models are never removable. Every `if v1 else v2` is permanent, and
  they accumulate at exactly the rate the format evolves.
- Every consumer of a model attribute would have to know the format version to interpret it — which
  is the weaker-form problem of §1 wearing a different hat, since a consumer that forgets to check
  reads a v1 value as if it were v2.

Normalize-on-read has none of these. The version-specific logic lives in one function, in one file,
and a reader's model code is single-version forever. It composes with Control A for free: the upcast
runs *before* strict keys, so a key that v2 renames or drops is already gone by the time
`extra="forbid"` sees the dict.

**Dropping a version from the set is a separate, announced break.** It requires its own CHANGELOG
entry and its own version bump, and it is the only event that forces authored files to actually be
edited. That — not the introduction of `v2` — is the moment a file-rewriting migration tool would
earn its keep (§10).

This section is policy, not implementation: there is no `v2`, so there is no `_v1_to_v2` to write.
What it fixes is that an implementer arriving at the first semantic change would otherwise have had
to invent the accept path under time pressure, with a production break as the cost of choosing wrong.

### 4.5 Two constants, two jobs *(rev. 3)*

Revisions 1 and 2 both wrote `SUPPORTED_FORMAT_VERSIONS` as a single frozenset used by a model-level
validator. Review showed that this cannot survive contact with §4.4: **"the models only ever
implement the newest format" and "the model validator accepts the supported set" cannot both be
true.** If the model accepts `v1`, then after `_v1_to_v2` runs you hold a v2-shaped object stamped
`format_version: "v1"`, and every consumer reading that attribute is misinformed — §1's weaker-form
problem, reached from a third direction. If the model accepts only `v2`, then the constant it
validates against is not the reader's supported set, and §4's description of it was wrong.

The split:

| Constant | Value today | Who reads it | Question it answers |
|---|---|---|---|
| `READABLE_FORMAT_VERSIONS` | `frozenset({"v1"})` | the `from_yaml` dispatcher, on the **raw dict** | "can this reader carry this file forward?" |
| `CURRENT_FORMAT_VERSION` | `"v1"` | the model — its field default and its **only** legal value | "is this object in the format the models implement?" |

**The upcast rewrites the key.** `_v1_to_v2` sets `format_version` to `"v2"` as part of producing a
v2-shaped dict. So a model never sees a non-current value, and a `Schema` in hand always states the
format its own fields are in.

This resolves three ambiguities that one constant could not:

1. **The field default.** A directly-constructed `Schema()` is current-format by construction, so its
   default must be `CURRENT_FORMAT_VERSION`. A file with no stamp is `v1` regardless of what is
   current. One default cannot serve both — so the missing-key default lives in the dispatcher, which
   reads the raw dict *before* the model has defaults to apply.
2. **Rejection authority.** The dispatcher rejects what it cannot read (`v3`, with no upcast chain);
   the model rejects what is not current. Both raise, and they are not redundant: the model's check
   is what catches an upcast that forgot to rewrite the key. Without the split, two sites reject
   using one constant for two meanings — the drift this section's own bullet cites `errors.py` to
   argue against.
3. **What criterion 5 pins.** `from_yaml` rejection is the dispatcher's; direct-construction
   rejection is the model's. Criterion 5 tests both, and now says which is which.

Today both constants are `"v1"`, which is exactly why two revisions of this document read fine with
one name. The cost of the split is one extra constant; the cost of not splitting is discovered at
the first semantic change, in production, by an implementer who inherited a contradiction.

## 5. `ContractFormatError`

### 5.1 Where it is raised

**Only at the `from_yaml` boundary** of `Schema` and `Contract`. It wraps `pydantic.ValidationError`
and `yaml.YAMLError`. It does **not** wrap `OSError` — an unreadable file is not a malformed one.

The wrapped region is the whole of `from_yaml`, which under §4.4 is *read YAML → upcast → validate*.
So when an upcast eventually exists, its failures are `ContractFormatError` too — a file that cannot
be carried forward to the current format is a malformed file from the caller's side, and splitting
that into a second exception type would make consumers handle two errors that need the same
response.

Direct model construction (`Field(name=..., type=...)`) keeps raising `ValidationError` unchanged.
This is deliberate and it is why the boundary is drawn here: `tests/test_types.py` has **15**
`pytest.raises(ValidationError)` sites against directly-constructed `Field`s (plus one
`pytest.raises(ValueError)` and the import on line 3 — an earlier draft reported the grep total, 16,
which is the wrong register for a document that pastes run output). None of them tests a file-format
concern. Wrapping at the model level would churn all 15 to prove nothing.

### 5.2 The message, and the conditional hint

The message always names the file and the specific failures. The **upgrade hint is conditional**:
it appears only when the error set contains an `extra_forbidden` entry or a `format_version` rejection.

> Unlike every other block in this document, the two messages below are **specified, not observed** —
> they are the target an implementer writes to, and no run produced them. The pydantic error *inputs*
> they are rendered from were verified (§3.2); the rendering is new work. This makes the single most
> user-visible deliverable in the design the least evidenced part of it, so **criterion 8 is the one
> that has to hold** — it is what converts this prose into something that fails when it is wrong.

This matters. A `min_length` on an int field is a genuine authoring error caught by the parent
spec's §4.1 applicability rules, and telling that author to upgrade their pin would send them to
debug the wrong thing entirely. Version skew and authoring mistakes arrive through the same code
path and must not leave through the same sentence.

```
ContractFormatError: schemas/peec/prompts_export/4.0.0.yaml declares keys this contract-core
(0.3.0) does not understand:
  fields.1.pattern
  fields.1.max_length

The file was likely authored against a newer contract-core. Upgrade the pin, or author the file
against 0.3.0. See CHANGELOG.md.
```

The version in the message is the **reader's** own `__version__`, and the keys are whatever a later
release added — the scenario is a `0.3.0` reader meeting a file from a hypothetical `0.4.0`. It is
deliberately *not* the `0.1.0`/`0.2.0` case of §1: those readers cannot produce this message at all,
which is the residual §6 records.

versus, for a real authoring error, the same exception type with no hint:

```
ContractFormatError: schemas/peec/prompts_export/3.0.0.yaml is not a valid schema:
  fields.0: field 'position': min_length applies to string, not 'int'
```

#### 5.2.1 The message is not what the operator reads *(rev. 3)*

Everything above describes the **exception**. `contract lint` — the command whose entire job is a
readable diagnostic, and the surface an operator actually meets — does not print it.
[`cli.py:46`](../../../src/contract_core/cli.py#L46) returns
`str(exc.errors()[0]["msg"]).removeprefix("Value error, ")`: the **first error only**, and for
`extra_forbidden` pydantic's `msg` carries no `loc`. Run against the §5.2 scenario, with strict keys
applied and a schema file declaring two unknown keys (`pattern`, `max_length`):

```
what the operator sees from contract lint:
  - Extra inputs are not permitted
```

No key names. No count — two unknown keys, one reported. No upgrade hint. The operator goes and
debugs their YAML by hand.

**Every criterion in revision 2 was green in that state.** Criterion 8 asserts on the exception,
criterion 10 asserts "not a traceback," and both pass while the deliverable is useless. This is
§4.4's own thesis landing one section later: the accept path got specified and the render path did
not, so nothing pointed at it.

So `ContractFormatError` carries an **attribute surface**, not just a rendered string:

| Attribute | Type | Purpose |
|---|---|---|
| `.path` | `str` | the file, so a caller can group or re-report by artifact |
| `.errors` | `list[tuple[str, str]]` | `(loc, msg)` per failure — the full set, not the first |
| `.hint` | `str \| None` | the upgrade sentence when §5.2's condition holds, else `None` |

`cli.py` renders from `.errors` — one diagnostic line per offending key path — and appends `.hint`
when present. `str(exc)` composes the same parts, so the library caller and the CLI cannot drift.

These three names are **frozen surface** in the same sense as `FieldDiff`'s field names (§5.3): a
consumer reads them to build custom handling, so renaming one is a breaking change.

### 5.3 Public API

`ContractFormatError` is exported from `contract_core`. The frozen surface goes **5 → 6**:

```python
FROZEN_SURFACE = {
    "ContractFormatError",   # new in 0.3.0
    "ContractRuntime",
    "ContractViolation",
    "FieldDiff",
    "__version__",
    "load_runtime",
}
```

Under R9 §3.2 that is a deliberate, reviewed act requiring a minor bump, and
`tests/test_public_api.py` is what makes it impossible to do silently.

**It subclasses `ValueError`.** `pydantic.ValidationError` already does — verified,
`issubclass(pydantic_core.ValidationError, ValueError) is True` — so any consumer catching
`ValueError` around `load_runtime` today keeps working. The surface grows; nothing breaks.

**It is not a `ContractViolation`.** A malformed contract file and a data violation are different
events with different audiences: one is a bug in an authored artifact, the other is drift in data.
Consumers catch `ContractViolation` to handle bad data — routing a malformed YAML file into that
handler would report a data problem that does not exist.

A second benefit: `pydantic.ValidationError` currently escapes `load_runtime` to library callers,
which makes pydantic a de-facto part of this package's API. Wrapping at the boundary ends that.

### 5.4 `cli.py`

Two changes, and the first one is the deliverable rather than a tidy-up.

**`_load_failure` renders from `.errors`, not from `errors()[0]["msg"]`.** Its `ValidationError` and
`yaml.YAMLError` arms collapse into one `ContractFormatError` arm; the `OSError` arm stays, per §5.1.
But collapsing the arms is not the point — §5.2.1 is. `_load_failure` returns a `str | None` today,
which structurally cannot carry per-key detail for a multi-error failure. It returns the **rendered
lines** for the file, and `lint` prints each. Criterion 14 is what holds this.

**`lint` needs an arm it has never had.** [`cli.py:66`](../../../src/contract_core/cli.py#L66) calls
`Contract.from_yaml(contract_path)` bare — a malformed *contract* file tracebacks today, and would
traceback as `ContractFormatError` after. That is pre-existing, not caused here, but this design is
what makes it reachable through a new exception type while claiming `lint` reports diagnostics rather
than tracebacks. Same treatment as `_load_failure`: catch, render, exit non-zero.

`lint` must keep reporting diagnostics rather than tracebacks — the behavior `0.2.0` added and the
malformed fixtures at `tests/fixtures/schemas_malformed/` exist to pin.

## 6. The residual — stated, not solved

**Nothing in this design helps a reader already in the wild.** `0.1.0` and `0.2.0` neither forbid
extras nor check `format_version`, so a `0.1.0` runtime will go on silently dropping `0.2.0`'s
constraint keys forever. No change to an authored file can reach a reader that was never taught to
look.

**R10 buys the next format break, not the last one.** The R10 row must say this. A row marked closed
that implies the `0.1.0`→`0.2.0` gap is sealed would be a worse artifact than the open row is now.

The controls for the existing gap are not code:

1. A **minimum supported reader** statement in [`CHANGELOG.md`](../../../CHANGELOG.md) and
   [`docs/consuming-repo-setup.md`](../../consuming-repo-setup.md): consuming repos pin
   `contract-core >= 0.3.0`, and the reason is that earlier readers silently ignore constraints.
2. **The value-constraints spec's §4.3 convention holds** — a constraint rides a major *schema*
   bump, so a `@1`-pinned consumer never resolves a file carrying keys its reader lacks. This is
   author discipline, not a control, and it is now explicitly the compensating control for a gap
   code cannot reach.

## 7. Deliberately out of scope

**`source` and `sink` stay `dict[str, Any]`.** They are the one part of the authored format that
keeps ignore-semantics, which is uncomfortable given §1 — so it is recorded rather than left quiet.
Verified: `grep` for `source`/`sink` across `runtime.py` and `compile/*.py` returns **no reads**.
Nothing in this codebase interprets them; they are documentation that happens to be structured.
Tightening them requires first deciding what they mean, which is a separate design with a separate
question ("what *is* a source?"), and answering it as a side effect of a format-versioning change
would be exactly the speculative scope this repo's §15 keeps pruning.

**The `json_schema` payload body stays arbitrary.** It is a foreign schema document by definition —
JSON Schema's own extensibility rules govern it, not this format's.

Both remain the honest hole in Control A's coverage. Neither is closed here.

## 8. Considered and rejected

**`apiVersion` alone, per the R10 row as written.** Rejected because it protects nothing on its own.
A stamp is only read by a reader that knows to read it, so it does nothing for the `0.1.0` and
`0.2.0` readers that constitute the live risk — and against a *future* additive change it is
strictly weaker than strict keys, since it depends on an author remembering to bump a field. Strict
keys need no one to remember anything.

**Strict keys alone.** Tempting on YAGNI grounds, and it does close §1 entirely. Rejected because
§3.3 is a real gap with no other cover, and the cost of Control B — one optional field, one
frozenset, one validator — is small enough that deferring it means paying the deprecation cost of
introducing a required-ish top-level key later, into files already in production.

**Format semver (`apiVersion: "1.1"`).** Minor-vs-major reasoning only pays off if a reader does
partial acceptance — accept `1.x`, tolerate keys it does not know. That is the silent weakening of
§1 with a version number attached. If a reader must refuse anything it cannot fully understand, the
minor component carries no decision, and the scheme collapses to major-only.

**A requirement floor (`requires: contract-core >= 0.2`).** Genuinely tempting: it answers the
question an old reader actually has, which `apiVersion: v1` does not. Rejected because it writes one
implementation's version numbers into a portable format. Decision #1 and R6 both anticipate a JS
reader of these same files (Phase 3), and `requires: contract-core >= 0.2` is a false statement the
moment one exists. It also duplicates the `pyproject.toml` pin — in a hand-maintained field, where
the two can disagree.

**An annotation escape hatch (`meta:` dict, or `x-` prefixed keys).** Rejected as unneeded: nobody
is blocked today, and YAML `#` comments already carry owner and rationale notes. A passthrough slot
is also a slot people put semantics into, which reintroduces unread-but-meaningful keys — the exact
shape of §1. If structured metadata is genuinely wanted later, adding a named key is the additive
change these two controls are built to make safe.

**Keeping the name `apiVersion`** and having `to_odcs` strip or translate it. Rejected: a strip step
is code written to manage a collision that costs nothing to avoid, and it would not touch the second
and larger objection — the casing inconsistency (§4.3). Renaming needs no code at all.

**A warn-then-enforce ladder for format parsing**, mirroring `observe`/`warn`/`enforce`. Rejected
because the ladder exists for *data*, where a warn phase buys calibration against real traffic
before enforcing. A malformed artifact needs no calibration, and §3.1 shows the enforce-now cost is
zero. More decisively: a warning in a batch job's log **is** the silent weakening of §1. The whole
point is that this failure stops being survivable-by-not-noticing.

## 9. Falsifiable criteria

1. A schema file carrying a key from a hypothetical future format (`fields[0].future_key`) raises
   `ContractFormatError` — it does **not** parse and validate a weaker form. *This is §1 as a
   literal test, and it is the criterion the design exists for.*
2. Each of `Schema`, `Field`, `Contract`, `BoundarySpec` rejects an unknown key at its own level.
3. A realistic typo (`requird: true`) is rejected, rather than silently defaulting `required`.
4. All extra keys are reported in one error, at every nesting level (§3.2), not just the first.
5. **Through `from_yaml`**: `format_version` absent → parses as `v1`; `format_version: v1` → parses;
   `format_version: v2` → `ContractFormatError` naming both the found value and the supported set.
   The entry path is named because §5.1 draws the wrapping boundary there and nowhere else —
   `Schema(format_version="v2")` constructed directly still raises `ValidationError`, exactly as
   criterion 9 requires for `Field`. An implementer who wraps at the validator instead satisfies
   this criterion and breaks that one.
6. `Schema.from_yaml` and `Contract.from_yaml` raise `ContractFormatError` and never leak
   `pydantic.ValidationError` or `yaml.YAMLError`.
7. `ContractFormatError` is catchable as `ValueError`, and is **not** a `ContractViolation`.
8. The upgrade hint appears for an unknown-key failure and is **absent** for an applicability
   failure (`min_length` on an int field) — §5.2.
9. `Field(name="brand", type="string", minimum=1)` still raises `ValidationError`, unwrapped:
   `tests/test_types.py` passes untouched.
10. `contract lint` reports the malformed fixtures as diagnostics with a clean exit path, not as
    tracebacks — the `0.2.0` behavior survives the exception-type change.
11. `set(contract_core.__all__)` is exactly the six names of §5.3.
12. Every pre-existing test still passes, and **exactly one is edited**: `FROZEN_SURFACE` in
    `tests/test_public_api.py`, 5 → 6. That edit is not an exception to the rule, it is the rule
    working — `test_public_surface_is_frozen` exists to fail on a surface change, and R9 §3.2
    requires the change be conscious and reviewed. Nothing else already green goes red or gets
    rewritten to stay green, and no fixture is edited. **Re-baseline the count before relying on
    it** — `186` is a reading taken on 2026-07-22 at `0.2.0`, not a constant, and any commit between
    then and implementation moves it. The invariant is the sentence, not the integer.
13. `format_version` does **not** appear in the ODCS export (§4.3, last paragraph). The enforcement
    for this is **pre-existing, not new work**: the vendored ODCS schema sets both
    `additionalProperties: false` and `unevaluatedProperties: false` at top level, and
    `tests/test_compile_odcs.py` already runs `validate_odcs` over real compile output at **nine**
    call sites. Verified against the vendored schema:

    ```
    validate_odcs(doc | {"format_version": "v1"})
      -> jsonschema.ValidationError: Additional properties are not allowed
         ('format_version' was unexpected)
    ```

    A leak fails the existing suite the moment it is introduced. This was a §11 "confirm" row in
    rev. 1 — a claim with no check, which is the defect class this document's own preamble
    diagnoses, relocated from behavior to policy.
14. **`contract lint` on a file with two unknown keys names both key paths and prints the hint.**
    Not the exception — the **stdout an operator reads** (§5.2.1). Criterion 8 asserts on the
    exception object and passes today against a diagnostic that reads, in full,
    `Extra inputs are not permitted`. This criterion is the one that fails in that state. It also
    pins the count: two unknown keys produce two diagnostic lines, not one.
15. `contract lint` on a **malformed contract file** reports a diagnostic and exits non-zero rather
    than raising through `cli.py:66` (§5.4). This path has never had a handler.

## 10. Deliberately not built

- **A migration tool**, and **`_v1_to_v2` itself.** With `v1` the only format version there is
  nothing to migrate between, and building the migrator before the migration is the
  extension-point-with-no-caller mistake the parent spec's §2 already declined once. §4.4 settles
  *where* an upcast will live and *what shape* it takes without writing one — policy is free, code
  is not. Note that §4.4's in-memory upcast never rewrites a file; a **file-rewriting** tool becomes
  interesting only when a version is dropped from the supported set, which is a separate announced
  break.
- **Anything retroactive for `0.1.0` / `0.2.0` readers.** §6 — impossible, documented instead.
- **`source` / `sink` schemas.** §7.
- **A `lint` rule enforcing the value-constraints spec's §4.3 major-schema-bump convention.** It is
  the compensating control in §6 and enforcing it is worth doing, but it reasons about *schema*
  version history rather than format keys — a different input and a different design.

## 11. Edit sites

| File | Change |
|---|---|
| `src/contract_core/schema.py` | `extra="forbid"`; `format_version` field + validator |
| `src/contract_core/types.py` | `extra="forbid"` on `Field` |
| `src/contract_core/contract.py` | `extra="forbid"` on `Contract` + `BoundarySpec`; `format_version` |
| `src/contract_core/errors.py` | `ContractFormatError`, subclassing `ValueError`, with `.path` / `.errors` / `.hint` (§5.2.1) |
| `src/contract_core/__init__.py` | export it; `__version__` → `0.3.0` |
| `src/contract_core/cli.py` | `_load_failure` renders per-error from `.errors`; **new arm at line 66** for the contract file (§5.4) |
| `src/contract_core/compile/odcs.py` | **none** — non-export is criterion 13, already enforced |
| `tests/test_public_api.py` | `FROZEN_SURFACE` 5 → 6 |
| `tests/` (new) | criteria §9 |
| `CHANGELOG.md` | `0.3.0` entry; **BREAKING — unknown keys in authored files now fail; previously ignored** (§3.1); minimum-supported-reader statement |
| `docs/consuming-repo-setup.md` | pin `>= 0.3.0` and why; **the strict-keys rule**; `format_version` as a writable key |
| `docs/superpowers/specs/2026-07-16-data-contract-system-design.md` | R10 row + §15 item 3, closed **with** the §6 residual |

### 11.1 Propagation paths — no edit expected, and that is a conclusion *(rev.)*

`ContractFormatError` now escapes from wherever `from_yaml` is called. The full set of call sites,
enumerated rather than assumed:

| Call site | Path | Expected edit |
|---|---|---|
| [`resolver.py:45`](../../../src/contract_core/resolver.py#L45) | exact-version resolve | none |
| [`resolver.py:52`](../../../src/contract_core/resolver.py#L52) | major-pin glob resolve | none |
| [`runtime.py:325`](../../../src/contract_core/runtime.py#L325) | `load_runtime` → `Contract.from_yaml` | none |
| [`cli.py:42`](../../../src/contract_core/cli.py#L42) | `lint` → `Schema.from_yaml` | render per-error (§5.4) |
| [`cli.py:66`](../../../src/contract_core/cli.py#L66) | `lint` → `Contract.from_yaml` | **new arm — has none today** (§5.4) |

`Resolver.resolve` has **two** call sites, not one, and neither catches anything today — so a
malformed schema reached during resolution propagates out of `load_runtime` as
`ContractFormatError`. That is the intended public behavior (§5.3: it is catchable as `ValueError`,
so nothing that catches broadly today breaks), which is *why* no edit is expected.

"No edit needed" is a claim that has to be checked, not a row worth omitting: `resolver.py` was
missing from the first draft of this table, and an implementer reading it would have had no signal
that resolution is on the new exception's path at all. An implementer should confirm each row rather
than inherit it — this table is reasoning, not a run.

`cli.py:66` is the row that proves the point. Rev. 1 added it and marked it "§5.4," which read as
covered; §5.4 discussed only `_load_failure`, so the one call site on this list with **no handler at
all** was the one the table implied was handled. Criterion 15 now pins it.

### 11.2 Why `consuming-repo-setup.md` needs more than a pin *(rev. 3)*

That file is not only install instructions — it documents the authored format *for authors*, including
`enum` / `minimum` / `maximum` / `min_length` under "Value constraints." Scoping its edit to "pin
`>= 0.3.0`" would ship a format whose newest rule (unknown keys now fail) and newest writable key
(`format_version`) appear in no author-facing document. An author's first encounter with strict keys
would then be a lint error for a rule nobody wrote down.

Release: **`0.3.0`**, minor under 0.x semantics — the public surface changed (§5.3), and per
`CHANGELOG.md`'s own preamble a 0.x minor may carry breaking changes to the authored format.
