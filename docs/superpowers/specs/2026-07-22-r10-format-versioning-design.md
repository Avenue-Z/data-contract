# Versioning the authored format — strict keys first, `format_version` second

**Status:** designed 2026-07-22, **revised once after review (2026-07-22)**, unimplemented.
**Closes:** R10, with a stated residual (§6). Does not close it silently.
**Parent spec:** [2026-07-16-data-contract-system-design.md](2026-07-16-data-contract-system-design.md)
— read R10 in §14, §15 item 3, decision #1 (Portable Core), and R6.
**Sibling:** [2026-07-21-value-constraints-design.md](2026-07-21-value-constraints-design.md) §4.3,
whose major-schema-bump convention is the only thing standing in for this design today.

> **On evidence.** The parent spec was revised three times, and all three revisions corrected the
> same defect: a behavioral claim asserted without running it. Every behavioral claim in this
> document was executed against this repo at `0.2.0` (pydantic 2.13.4) before it was written down.
> Runs are pasted, not paraphrased. Where something was *not* run, it says so.
>
> **Revision 1** held every behavioral claim under review — they were independently reproduced — and
> broke on a different axis: **naming and enumeration**, the two things running the code does not
> check. The draft named its new key `apiVersion` without noticing that `odcs.py:84` already emits
> that key with an unrelated meaning, and that it would be the only camelCase key in an
> eighteen-key snake_case format (§4.3, marked *(rev.)*). Its edit-site table also omitted
> `resolver.py`, which calls `Schema.from_yaml` **twice** and is therefore on the new exception's
> propagation path (§11.1, marked *(rev.)*).
>
> The lesson is worth keeping distinct from the parent spec's. There, unverified *behavior* was the
> defect and running the code was the fix. Here the code was run and the design was still wrong,
> because "does this name already mean something else in this repo?" and "what else calls this
> function?" are grep questions, not runtime questions. **An evidence discipline aimed only at
> execution will pass a design that collides with the codebase it is being added to.**

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

### 3.1 Blast radius — measured, not estimated

The four edits were applied and the full suite run:

```
186 passed, 2 warnings in 3.45s
```

**Zero failures.** No fixture, no test, and no valid authored file carries an undeclared key today,
so strict keys break nothing that currently works. The two warnings are the pre-existing
`schema`-shadows-`BaseModel` notices, unrelated to this change.

This is the whole argument for shipping Control A first: it closes §1 completely, and it costs
nothing to adopt.

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

- **Declared as `format_version: str = "v1"`.** Missing defaults to `v1`, because a missing stamp can
  only mean "authored before stamps existed" — which *is* `v1`. No existing file breaks, and none
  needs editing.
- **`SUPPORTED_FORMAT_VERSIONS = frozenset({"v1"})`**. A field validator rejects anything outside it,
  naming both what it found and what it supports. It lives in **`types.py`** and is imported by both
  `schema.py` and `contract.py` — one definition, for the reason `errors.py` gives for `Problem`:
  two copies of the same constant can drift, and a `Schema` and a `Contract` disagreeing about which
  format versions exist is precisely the mis-parse this control prevents. `types.py` imports neither
  module, so there is no cycle.
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

### 4.2 Interaction with Control A

The two compose without special-casing. `format_version` becomes a declared field, so it passes strict
keys; an unsupported *value* is rejected by the validator, not by the extra-key rule. Verified: with
strict keys applied and `format_version` **not yet declared**, `format_version: v2` is rejected as
`extra_forbidden` — correct behavior, and the reason both controls must ship in the **same** release
rather than across two.

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

## 5. `ContractFormatError`

### 5.1 Where it is raised

**Only at the `from_yaml` boundary** of `Schema` and `Contract`. It wraps `pydantic.ValidationError`
and `yaml.YAMLError`. It does **not** wrap `OSError` — an unreadable file is not a malformed one.

Direct model construction (`Field(name=..., type=...)`) keeps raising `ValidationError` unchanged.
This is deliberate and it is why the boundary is drawn here: `tests/test_types.py` asserts
`ValidationError` in 16 places against directly-constructed `Field`s, and none of them is testing a
file-format concern. Wrapping at the model level would churn all 16 to prove nothing.

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

[`cli.py`](../../../src/contract_core/cli.py) catches `ValidationError` and `yaml.YAMLError` in
separate arms. Those two collapse into one `ContractFormatError` arm. The `OSError` arm stays, per
§5.1. `lint` must keep reporting diagnostics rather than tracebacks — the behavior `0.2.0` added and
the malformed fixtures at `tests/fixtures/schemas_malformed/` exist to pin.

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
5. `format_version` absent → parses as `v1`. `format_version: v1` → parses. `format_version: v2` →
   `ContractFormatError` naming both the found value and the supported set.
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
12. Every pre-existing test still passes, with no edits to them and no edits to any fixture (§3.1).
    New tests for criteria 1–11 are added alongside; the count grows, but nothing already green goes
    red or gets rewritten to stay green. **Re-baseline the count before relying on it** — `186` is a
    reading taken on 2026-07-22 at `0.2.0`, not a constant, and any commit between then and
    implementation moves it. The invariant is "no pre-existing test changed," not the integer.

## 10. Deliberately not built

- **A migration tool.** With `v1` the only format version, there is nothing to migrate between.
  Building the migrator before the migration is the extension-point-with-no-caller mistake the
  parent spec's §2 already declined once.
- **Anything retroactive for `0.1.0` / `0.2.0` readers.** §6 — impossible, documented instead.
- **`source` / `sink` schemas.** §7.
- **A `lint` rule enforcing the value-constraints spec's §4.3 major-schema-bump convention.** It is
  the compensating control in
  §6 and enforcing it is worth doing, but it reasons about *schema* version history rather than
  format keys — a different input and a different design.

## 11. Edit sites

| File | Change |
|---|---|
| `src/contract_core/schema.py` | `extra="forbid"`; `format_version` field + validator |
| `src/contract_core/types.py` | `extra="forbid"` on `Field` |
| `src/contract_core/contract.py` | `extra="forbid"` on `Contract` + `BoundarySpec`; `format_version` |
| `src/contract_core/errors.py` | `ContractFormatError`, subclassing `ValueError` |
| `src/contract_core/__init__.py` | export it; `__version__` → `0.3.0` |
| `src/contract_core/cli.py` | collapse two except-arms into one; keep `OSError` |
| `src/contract_core/compile/odcs.py` | **none** — but confirm `format_version` is not exported (§4.3) |
| `tests/test_public_api.py` | `FROZEN_SURFACE` 5 → 6 |
| `tests/` (new) | criteria §9 |
| `CHANGELOG.md` | `0.3.0` entry; minimum-supported-reader statement |
| `docs/consuming-repo-setup.md` | pin `>= 0.3.0`, and why |
| `docs/superpowers/specs/2026-07-16-data-contract-system-design.md` | R10 row + §15 item 3, closed **with** the §6 residual |

### 11.1 Propagation paths — no edit expected, and that is a conclusion *(rev.)*

`ContractFormatError` now escapes from wherever `from_yaml` is called. The full set of call sites,
enumerated rather than assumed:

| Call site | Path | Expected edit |
|---|---|---|
| [`resolver.py:45`](../../../src/contract_core/resolver.py#L45) | exact-version resolve | none |
| [`resolver.py:52`](../../../src/contract_core/resolver.py#L52) | major-pin glob resolve | none |
| [`runtime.py:325`](../../../src/contract_core/runtime.py#L325) | `load_runtime` → `Contract.from_yaml` | none |
| [`cli.py:42`](../../../src/contract_core/cli.py#L42) | `lint` → `Schema.from_yaml` | §5.4 |
| [`cli.py:66`](../../../src/contract_core/cli.py#L66) | `Contract.from_yaml` | §5.4 |

`Resolver.resolve` has **two** call sites, not one, and neither catches anything today — so a
malformed schema reached during resolution propagates out of `load_runtime` as
`ContractFormatError`. That is the intended public behavior (§5.3: it is catchable as `ValueError`,
so nothing that catches broadly today breaks), which is *why* no edit is expected.

"No edit needed" is a claim that has to be checked, not a row worth omitting: `resolver.py` was
missing from the first draft of this table, and an implementer reading it would have had no signal
that resolution is on the new exception's path at all. An implementer should confirm each row rather
than inherit it — this table is reasoning, not a run.

Release: **`0.3.0`**, minor under 0.x semantics — the public surface changed (§5.3), and per
`CHANGELOG.md`'s own preamble a 0.x minor may carry breaking changes to the authored format.
