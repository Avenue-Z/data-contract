# Value Constraints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a schema author declare `enum`, `minimum`, `maximum`, and `min_length` on a field, and
have every boundary enforce them — closing the gap where nonsense values pass validation silently.

**Architecture:** Four optional keys on `Field`, validated for type-applicability at schema load.
Three compilers gain constraint output (Pandera checks, JSON Schema keywords, ODCS
`logicalTypeOptions` + `quality` rules). `_validate_tabular` gains a drop rule and an aggregation step
so a row-level failure reports a count and samples instead of one arbitrary row. `FieldDiff` gains a
`value` problem variant and three typed fields.

**Tech Stack:** Python 3.13, Pydantic v2, Pandera 0.32.1, `jsonschema`, PyYAML, `click`, `pytest`,
`ruff`, `mypy --strict`.

**Source spec:** [2026-07-21-value-constraints-design.md](../specs/2026-07-21-value-constraints-design.md).
Read §4.1, §5.2, §5.2.1, §5.2.2, §5.4.1 and §5.4.2 before starting. Section references below point
into that document.

**Branch:** cut `feat/value-constraints` from `dev`. PR base is `dev` (see `CONTRIBUTING.md` —
**never push to `main`**).

## Global Constraints

Every task inherits these. Values are copied verbatim from the design.

- **The four constraints are `enum`, `minimum`, `maximum`, `min_length`.** No `pattern`, no exclusive
  bounds, no `maxLength`, no `multipleOf` (§2, §10).
- **Applicability** (§4.1): `minimum`/`maximum` on `int`/`float` only; `min_length` on `string` only;
  `enum` on `string`/`int`/`bool` only. `enum` must be a non-empty list whose values match the
  declared type.
- **Pandera checks are identified by `error=`, never by `name=`** (§5.2). Verified against 0.32.1:
  `failure_cases["check"]` is populated from `error`. `pa.Check.isin([0,1], name="enum")` yields
  `"isin([0, 1])"` and would be classified as `retyped`.
- **Every value check sets `ignore_na=True` explicitly** (§4.2). It is already the default; the
  guarantee must not rest on a pinned dependency's default.
- **`coerce=False` stays** and the R8 family check is unchanged in behavior. Nothing mutates data to
  make it pass.
- **No new public names.** The surface stays the five frozen names; `FieldDiff` gains fields.

---

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `src/contract_core/types.py` | `Field` gains four constraint keys + applicability validation | 1 |
| `src/contract_core/compile/jsonschema_compile.py` | constraints → JSON Schema keywords | 2 |
| `src/contract_core/compile/pandera_compile.py` | constraints → named Pandera checks | 3 |
| `src/contract_core/errors.py` | `Problem` (single definition) + `FieldDiff`'s three new fields | 4 |
| `src/contract_core/runtime.py` | import `Problem`; `hard` gains `value`; drop rule + aggregation; payload branch | 4, 5, 6 |
| `src/contract_core/compile/odcs.py` | bounds → `logicalTypeOptions`; enum + nulls → `quality` | 7 |
| `src/contract_core/cli.py` | `lint` walks resolver-visible schema files, catches `ValidationError` | 8 |

---

### Task 1: `Field` gains the four constraints, validated at load

**Files:**
- Modify: `src/contract_core/types.py`
- Test: `tests/test_types.py`

**Interfaces:**
- Produces: `Field.enum: list[Any] | None`, `Field.minimum: float | None`,
  `Field.maximum: float | None`, `Field.min_length: int | None`. All default `None`, so every
  existing schema stays valid. A violation of §4.1 raises `pydantic.ValidationError` at
  `Schema.from_yaml`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_types.py`:

```python
import pytest
from pydantic import ValidationError

from contract_core.types import Field


def test_constraints_default_to_none_so_existing_schemas_are_valid():
    f = Field(name="x", type="int")
    assert (f.enum, f.minimum, f.maximum, f.min_length) == (None, None, None, None)


def test_numeric_bounds_are_accepted_on_numeric_types():
    f = Field(name="sentiment", type="float", minimum=-1.0, maximum=1.0)
    assert (f.minimum, f.maximum) == (-1.0, 1.0)


def test_minimum_on_a_string_field_is_rejected():
    # Design §4.1: applicability is an authoring error, caught at load, not at validation.
    with pytest.raises(ValidationError, match="minimum/maximum apply to int/float"):
        Field(name="brand", type="string", minimum=1)


def test_min_length_on_an_int_field_is_rejected():
    with pytest.raises(ValidationError, match="min_length applies to string"):
        Field(name="rank", type="int", min_length=1)


def test_enum_on_a_datetime_field_is_rejected():
    # The targets disagree on date encoding (§4.1): JSON Schema sees an ISO string,
    # pandas sees a Timestamp.
    with pytest.raises(ValidationError, match="enum applies to string/int/bool"):
        Field(name="day", type="datetime", enum=["2026-01-01"])


def test_enum_on_a_float_field_is_rejected():
    with pytest.raises(ValidationError, match="enum applies to string/int/bool"):
        Field(name="score", type="float", enum=[0.0, 1.0])


def test_empty_enum_is_rejected():
    with pytest.raises(ValidationError, match="enum must not be empty"):
        Field(name="is_owned", type="int", enum=[])


def test_enum_values_must_match_the_declared_type():
    # `enum: ["0", "1"]` on an int field matches nothing and fails every row while
    # looking like a data problem (§4.1).
    with pytest.raises(ValidationError, match="do not match declared type"):
        Field(name="is_owned", type="int", enum=["0", "1"])


def test_bool_is_not_an_int_for_enum_purposes():
    # isinstance(True, int) is True in Python; the validator must not accept it.
    with pytest.raises(ValidationError, match="do not match declared type"):
        Field(name="is_owned", type="int", enum=[True, False])


def test_enum_is_accepted_on_int_string_and_bool():
    assert Field(name="a", type="int", enum=[0, 1]).enum == [0, 1]
    assert Field(name="b", type="string", enum=["x"]).enum == ["x"]
    assert Field(name="c", type="bool", enum=[True]).enum == [True]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_types.py -q`
Expected: FAIL — `TypeError`/`ValidationError` about unexpected keyword `minimum` on the first new
test that passes a constraint.

- [ ] **Step 3: Implement**

Replace the body of `src/contract_core/types.py` above `PANDAS_DTYPE` with:

```python
from typing import Any, Literal

from pydantic import BaseModel, model_validator

FieldType = Literal["string", "int", "float", "bool", "date", "datetime"]

# Design §4.1. Narrow on purpose: a constraint is allowed only where all three compile
# targets agree what it means.
_BOUND_TYPES = {"int", "float"}
_ENUM_TYPES = {"string", "int", "bool"}


def _value_matches_type(value: Any, declared: str) -> bool:
    # bool before int: isinstance(True, int) is True, so an unguarded int check would
    # accept `enum: [true, false]` on an int field.
    if declared == "bool":
        return isinstance(value, bool)
    if declared == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, str)


class Field(BaseModel):
    name: str
    type: FieldType
    required: bool = True
    nullable: bool = False
    # Value constraints (design §4). All optional: every pre-existing schema stays valid.
    enum: list[Any] | None = None
    minimum: float | None = None
    maximum: float | None = None
    min_length: int | None = None

    @model_validator(mode="after")
    def _constraints_match_the_declared_type(self) -> "Field":
        if (self.minimum is not None or self.maximum is not None) \
                and self.type not in _BOUND_TYPES:
            raise ValueError(
                f"field {self.name!r}: minimum/maximum apply to int/float, not {self.type!r}"
            )
        if self.min_length is not None and self.type != "string":
            raise ValueError(
                f"field {self.name!r}: min_length applies to string, not {self.type!r}"
            )
        if self.enum is not None:
            if self.type not in _ENUM_TYPES:
                raise ValueError(
                    f"field {self.name!r}: enum applies to string/int/bool, not {self.type!r}"
                )
            if not self.enum:
                raise ValueError(f"field {self.name!r}: enum must not be empty")
            bad = [v for v in self.enum if not _value_matches_type(v, self.type)]
            if bad:
                raise ValueError(
                    f"field {self.name!r}: enum values {bad!r} "
                    f"do not match declared type {self.type!r}"
                )
        return self
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_types.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite — nothing should regress**

Run: `pytest -q && ruff check . && mypy --strict`
Expected: all green. Every existing fixture schema omits the new keys, so all four default to `None`.

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/types.py tests/test_types.py
git commit -m "feat: declare value constraints on Field, validated at schema load"
```

---

### Task 2: JSON Schema compilation

**Files:**
- Modify: `src/contract_core/compile/jsonschema_compile.py`
- Test: `tests/test_compile_jsonschema.py`

**Interfaces:**
- Consumes: `Field.enum` / `.minimum` / `.maximum` / `.min_length` from Task 1.
- Produces: `to_json_schema(schema, *, open)` emits `enum` / `minimum` / `maximum` / `minLength` in
  each property. Signature unchanged. The private helper changes from
  `_field_schema(field_type: str, nullable: bool)` to `_field_schema(field: Field)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_compile_jsonschema.py`:

```python
from contract_core.compile.jsonschema_compile import to_json_schema
from contract_core.schema import Schema


def _schema(**field_kwargs):
    return Schema(schema="t", version="1.0.0", kind="tabular",
                  fields=[{"name": "f", "type": field_kwargs.pop("type", "int"),
                           **field_kwargs}])


def test_bounds_and_min_length_become_json_schema_keywords():
    js = to_json_schema(_schema(type="float", minimum=-1.0, maximum=1.0), open=True)
    assert js["properties"]["f"]["minimum"] == -1.0
    assert js["properties"]["f"]["maximum"] == 1.0

    js = to_json_schema(_schema(type="string", min_length=1), open=True)
    assert js["properties"]["f"]["minLength"] == 1


def test_enum_becomes_an_enum_keyword():
    js = to_json_schema(_schema(type="int", enum=[0, 1]), open=True)
    assert js["properties"]["f"]["enum"] == [0, 1]


def test_nullable_enum_includes_null():
    # Design §5.1: `enum` is NOT type-scoped, so a nullable field must list null or its
    # own `nullable: true` is contradicted.
    js = to_json_schema(_schema(type="int", enum=[0, 1], nullable=True), open=True)
    assert js["properties"]["f"]["enum"] == [0, 1, None]


def test_non_nullable_enum_does_not_include_null():
    js = to_json_schema(_schema(type="int", enum=[0, 1], nullable=False), open=True)
    assert None not in js["properties"]["f"]["enum"]


def test_unconstrained_field_gains_no_keywords():
    js = to_json_schema(_schema(type="int"), open=True)
    assert set(js["properties"]["f"]) == {"type"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_compile_jsonschema.py -q`
Expected: FAIL — `KeyError: 'minimum'`.

- [ ] **Step 3: Implement**

Replace `src/contract_core/compile/jsonschema_compile.py` entirely:

```python
from typing import Any

from contract_core.schema import Schema
from contract_core.types import JSON_SCHEMA_TYPE, Field


def _field_schema(field: Field) -> dict[str, Any]:
    base = dict(JSON_SCHEMA_TYPE[field.type])
    if field.nullable:
        t = base["type"]
        base["type"] = [t, "null"]
    if field.enum is not None:
        # `minimum`/`minLength` apply only to instances of their type, so null passes them
        # for free. `enum` is a flat set of permitted instances and is NOT type-scoped, so a
        # nullable field must list null explicitly or it rejects its own legal value
        # (design §5.1).
        base["enum"] = [*field.enum, None] if field.nullable else list(field.enum)
    if field.minimum is not None:
        base["minimum"] = field.minimum
    if field.maximum is not None:
        base["maximum"] = field.maximum
    if field.min_length is not None:
        base["minLength"] = field.min_length
    return base


def to_json_schema(schema: Schema, *, open: bool) -> dict[str, Any]:
    if schema.json_schema is not None:
        return schema.json_schema
    assert schema.fields is not None  # non-passthrough schema always has fields (validator)
    props = {f.name: _field_schema(f) for f in schema.fields}
    required = [f.name for f in schema.fields if f.required]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": bool(open),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_compile_jsonschema.py -q && pytest -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/contract_core/compile/jsonschema_compile.py tests/test_compile_jsonschema.py
git commit -m "feat: compile value constraints to JSON Schema keywords"
```

---

### Task 3: Pandera compilation — checks identified by `error=`

**Files:**
- Modify: `src/contract_core/compile/pandera_compile.py`
- Test: `tests/test_compile_pandera.py`

**Interfaces:**
- Consumes: the `Field` constraints from Task 1.
- Produces: `to_pandera(schema, *, strict)` attaches one check per constraint. Each sets
  `error="<constraint>"` where `<constraint>` is exactly `enum`, `minimum`, `maximum`, or
  `min_length`. `_family_check`'s `error` becomes `dtype_family:<type>`. Task 5 classifies on these
  strings; they are an interface, not a message.

> **Interim state, on purpose.** After this task a value violation is still reported as `retyped`,
> because the runtime classifier does not know the new check names until Task 5. Do not ship the
> branch between Task 3 and Task 5.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_compile_pandera.py`:

```python
import pandas as pd
import pandera.pandas as pa
import pytest

from contract_core.compile.pandera_compile import to_pandera
from contract_core.schema import Schema


def _validate(field_kwargs, values):
    """Validate one column, returning the list of (check, failure_case) pairs."""
    s = Schema(schema="t", version="1.0.0", kind="tabular",
               fields=[{"name": "f", "nullable": True, **field_kwargs}])
    ps = to_pandera(s, strict=False)
    try:
        ps.validate(pd.DataFrame({"f": values}), lazy=True)
        return []
    except pa.errors.SchemaErrors as err:
        return [(str(r["check"]), str(r["failure_case"]))
                for _, r in err.failure_cases.iterrows()]


def test_minimum_failure_is_named_minimum_not_a_rendered_expression():
    # Design §5.2: `failure_cases["check"]` comes from `error=`, NOT `name=`. Built with
    # `name=`, this reads "greater_than_or_equal_to(-1.0)" and the runtime calls it `retyped`.
    got = _validate({"type": "float", "minimum": -1.0}, [-9.0])
    assert [c for c, _ in got] == ["minimum"]


def test_maximum_and_enum_and_min_length_are_named_too():
    assert [c for c, _ in _validate({"type": "float", "maximum": 1.0}, [9.0])] == ["maximum"]
    assert [c for c, _ in _validate({"type": "int", "enum": [0, 1]}, [5])] == ["enum"]
    assert [c for c, _ in _validate({"type": "string", "min_length": 1}, [""])] == ["min_length"]


def test_the_family_check_error_is_machine_recognizable():
    # Task 5's drop rule identifies a dtype failure by this prefix. Prose here makes the
    # rule unbuildable (design §5.2.2).
    got = _validate({"type": "float"}, ["not-a-number"])
    assert any(c.startswith("dtype_family:") for c, _ in got)


def test_nulls_do_not_trip_value_checks():
    # Design §4.2: `nullable` is the sole null gate.
    assert _validate({"type": "float", "minimum": -1.0}, [None, 0.5]) == []
    assert _validate({"type": "int", "enum": [0, 1]}, [None, 1]) == []
    assert _validate({"type": "string", "min_length": 1}, [None, "ok"]) == []


def test_conforming_data_passes_every_constraint():
    # The true negative. A check that always fires passes any one-directional test.
    assert _validate({"type": "float", "minimum": -1.0, "maximum": 1.0}, [0.0, 1.0, -1.0]) == []
    assert _validate({"type": "int", "enum": [0, 1]}, [0, 1, 1]) == []
    assert _validate({"type": "string", "min_length": 1}, ["a", "bc"]) == []


def test_two_constraints_on_one_field_report_separately():
    got = _validate({"type": "float", "minimum": -1.0, "maximum": 1.0}, [-9.0, 9.0])
    assert sorted(c for c, _ in got) == ["maximum", "minimum"]


def test_unconstrained_field_keeps_only_the_family_check():
    got = _validate({"type": "int"}, ["nope"])
    assert [c for c, _ in got] == ["dtype_family:int"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_compile_pandera.py -q`
Expected: FAIL — `test_minimum_failure_is_named_minimum...` gets `[]` (no check emitted), and
`test_the_family_check_error_is_machine_recognizable` gets the prose error.

- [ ] **Step 3: Implement**

Replace `src/contract_core/compile/pandera_compile.py` entirely:

```python
import pandera.pandas as pa

from contract_core.families import dtype_satisfies
from contract_core.schema import Schema
from contract_core.types import Field

# The names the runtime classifies on (design §5.2.1). These strings are an interface
# between this module and `runtime._validate_tabular`, not human-facing text.
VALUE_CHECK_NAMES = frozenset({"enum", "minimum", "maximum", "min_length"})
DTYPE_CHECK_PREFIX = "dtype_family:"


def _family_check(field_type: str) -> pa.Check:
    """A non-mutating check that the column's physical dtype satisfies `field_type`.

    Replaces exact-dtype equality (R8): matches on logical type families so an
    inferred-but-equivalent dtype (int64 for a float, float64 for a nullable int,
    object vs str) passes, while a genuine type change (a stringified number, a
    real decimal where an int was declared) still fails. `coerce=False` stays the
    default so nothing is mutated to hide drift (success criterion #1).

    `error` carries a machine-recognizable token, not prose: pandera populates
    `failure_cases["check"]` from `error`, and Task 5's drop rule identifies a dtype
    failure by the prefix (design §5.2.2).
    """
    return pa.Check(
        lambda s: dtype_satisfies(field_type, s),
        name=f"{DTYPE_CHECK_PREFIX}{field_type}",
        error=f"{DTYPE_CHECK_PREFIX}{field_type}",
    )


def _value_checks(f: Field) -> list[pa.Check]:
    """One check per declared constraint, each identified by `error=` (design §5.2).

    `ignore_na=True` is pandera's default and is set explicitly anyway: §4.2 promises
    consumers that constraints skip nulls, and that promise must not rest on a pinned
    dependency's default.
    """
    checks: list[pa.Check] = []
    if f.enum is not None:
        checks.append(pa.Check.isin(list(f.enum), error="enum", ignore_na=True))
    if f.minimum is not None:
        checks.append(pa.Check.ge(f.minimum, error="minimum", ignore_na=True))
    if f.maximum is not None:
        checks.append(pa.Check.le(f.maximum, error="maximum", ignore_na=True))
    if f.min_length is not None:
        n = f.min_length  # bind per field: a closure over `f` would read the last field
        checks.append(pa.Check(lambda s: s.str.len() >= n, error="min_length",
                               ignore_na=True))
    return checks


def to_pandera(schema: Schema, *, strict: bool) -> pa.DataFrameSchema:
    if schema.kind != "tabular":
        raise ValueError(f"to_pandera requires kind 'tabular', got {schema.kind!r}")
    assert schema.fields is not None  # a tabular schema always has fields (Schema validator)
    columns = {
        f.name: pa.Column(
            dtype=None,  # dtype equality replaced by the family check below (R8)
            nullable=f.nullable,
            required=f.required,
            checks=[_family_check(f.type), *_value_checks(f)],
            coerce=False,  # load-bearing: coercion would hide type drift (criterion #1)
        )
        for f in schema.fields
    }
    return pa.DataFrameSchema(columns, strict=strict)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_compile_pandera.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest -q && ruff check . && mypy --strict`
Expected: all green. `dtype_family:<type>` still falls through the runtime's `else` branch to
`retyped`, exactly as the prose error did, so no existing test changes behavior.

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/compile/pandera_compile.py tests/test_compile_pandera.py
git commit -m "feat: compile value constraints to named Pandera checks"
```

---

### Task 4: `FieldDiff` gains the value fields; `Problem` gets one definition

**Files:**
- Modify: `src/contract_core/errors.py`
- Modify: `src/contract_core/runtime.py` (the `Problem` alias and the `hard` tuple)
- Test: `tests/test_errors.py`, `tests/test_public_api.py`

**Interfaces:**
- Produces: `Problem = Literal["missing", "retyped", "nullable", "extra", "value"]`, defined **once**
  in `errors.py` and imported by `runtime.py`. `FieldDiff` gains `constraint: str | None = None`,
  `violating_rows: int | None = None`, `samples: list[str] = []`.
- Consumed by: Tasks 5 and 6, which construct value diffs.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_errors.py`:

```python
from contract_core.errors import ContractViolation, FieldDiff


def test_structural_diffs_leave_the_value_fields_empty():
    d = FieldDiff(field="position", expected="int", observed="absent", problem="missing")
    assert d.constraint is None
    assert d.violating_rows is None
    assert d.samples == []


def test_a_value_diff_carries_a_typed_count_and_samples():
    # Design §6.2: a consumer must not have to regex a number out of prose.
    d = FieldDiff(field="sentiment", expected="float", observed="float64", problem="value",
                  constraint="maximum=1.0", violating_rows=3, samples=["1.4", "2.7"])
    assert d.violating_rows == 3
    assert d.samples == ["1.4", "2.7"]


def test_samples_default_is_not_shared_between_instances():
    a = FieldDiff(field="a", expected="int", observed="absent", problem="missing")
    b = FieldDiff(field="b", expected="int", observed="absent", problem="missing")
    a.samples.append("leaked")
    assert b.samples == []


def test_rendered_message_names_the_constraint_count_and_samples():
    exc = ContractViolation(
        boundary="prompts", schema_ref="peec.prompts_export@2.0.0", direction="input",
        diffs=[FieldDiff(field="sentiment", expected="float", observed="float64",
                         problem="value", constraint="maximum=1.0", violating_rows=3,
                         samples=["1.4", "2.7", "1.02"])],
    )
    msg = str(exc)
    assert "maximum=1.0" in msg
    assert "3 of" in msg or "3 rows" in msg
    assert "1.4" in msg


def test_structural_message_is_unchanged():
    exc = ContractViolation(
        boundary="prompts", schema_ref="peec.prompts_export@1.0.0", direction="input",
        diffs=[FieldDiff(field="position", expected="int", observed="absent",
                         problem="missing")],
    )
    assert str(exc) == (
        "peec.prompts_export@1.0.0 at input 'prompts': "
        "missing field 'position' expected int, observed absent"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_errors.py -q`
Expected: FAIL — unexpected keyword argument `constraint`.

- [ ] **Step 3: Implement `errors.py`**

Replace `src/contract_core/errors.py` entirely:

```python
from typing import Literal

from pydantic import BaseModel

# The single definition. `runtime.py` imports this rather than restating it: two copies
# of the same Literal can drift, and adding a fifth variant is when that starts to matter
# (design §7).
Problem = Literal["missing", "retyped", "nullable", "extra", "value"]


class FieldDiff(BaseModel):
    field: str
    expected: str
    observed: str
    problem: Problem
    # Value-violation detail (design §6.2). None / empty on every structural diff.
    # `expected` and `observed` keep their existing meanings — the declared type and the
    # observed dtype/state — so a consumer reading them does not break.
    constraint: str | None = None
    violating_rows: int | None = None
    samples: list[str] = []


class ContractViolation(Exception):
    def __init__(self, *, boundary: str, schema_ref: str, direction: str,
                 diffs: list[FieldDiff]) -> None:
        self.boundary = boundary
        self.schema_ref = schema_ref
        self.direction = direction
        self.diffs = diffs
        super().__init__(self._render())

    def _render(self) -> str:
        lines = []
        for d in self.diffs:
            head = f"{self.schema_ref} at {self.direction} '{self.boundary}': "
            if d.problem == "value":
                detail = f"value field '{d.field}' violates {d.constraint}"
                if d.violating_rows is not None:
                    detail += f" — {d.violating_rows} rows"
                if d.samples:
                    detail += f" (e.g. {', '.join(d.samples)})"
                lines.append(head + detail)
            else:
                lines.append(
                    head + f"{d.problem} field '{d.field}' "
                    f"expected {d.expected}, observed {d.observed}"
                )
        return "\n".join(lines)
```

- [ ] **Step 4: Implement the two `runtime.py` edits**

In `src/contract_core/runtime.py`, change the import from `errors`:

```python
from contract_core.errors import ContractViolation, FieldDiff, Problem
```

Delete the local alias (the line reading `Problem = Literal["missing", "retyped", "nullable",
"extra"]`). If `Literal` is now unused in that file, remove it from the `typing` import.

Then add `"value"` to the hard-failure tuple:

```python
        hard = [d for d in diffs if d.problem in ("missing", "retyped", "nullable", "value")]
```

- [ ] **Step 5: Update the frozen-surface test deliberately**

Append to `tests/test_public_api.py`:

```python
def test_field_diff_carries_the_value_violation_fields():
    # A deliberate, reviewed surface change (R9 §3.2 / design §7): `FieldDiff` gained
    # three fields and `problem` gained a "value" variant in 0.2.0. Consumers matching
    # exhaustively on `problem` will see a value they have not seen before.
    names = set(FieldDiff.model_fields)
    assert names == {"field", "expected", "observed", "problem",
                     "constraint", "violating_rows", "samples"}
```

- [ ] **Step 6: Run the tests**

Run: `pytest tests/test_errors.py tests/test_public_api.py -q && pytest -q && mypy --strict`
Expected: all green. The five frozen names are unchanged, so `test_public_surface_is_frozen` still
passes.

- [ ] **Step 7: Commit**

```bash
git add src/contract_core/errors.py src/contract_core/runtime.py \
        tests/test_errors.py tests/test_public_api.py
git commit -m "feat: FieldDiff carries typed value-violation detail; one Problem definition"
```

---

### Task 5: Value diffs in `_validate_tabular` — drop rule, then aggregation

**Files:**
- Modify: `src/contract_core/runtime.py` (`_validate_tabular`)
- Test: `tests/test_value_constraints.py` (create)
- Test fixture: `tests/fixtures/schemas/peec/prompts_export/2.0.0.yaml` (create)

**Interfaces:**
- Consumes: `VALUE_CHECK_NAMES` and `DTYPE_CHECK_PREFIX` from Task 3; `FieldDiff`'s new fields from
  Task 4.
- Produces: `_validate_tabular` returns one `FieldDiff` per `(field, check)` group for value
  failures, and one per field for structural failures.

**Why the order matters (design §5.2.2):** a value check against a wrong dtype does not return
`False`, it **raises**, and pandera records the `TypeError` as the failure case. Aggregating first
computes counts and samples off `TypeError` reprs and then discards them.

- [ ] **Step 1: Create the fixture schema**

Create `tests/fixtures/schemas/peec/prompts_export/2.0.0.yaml`:

```yaml
# tests/fixtures/schemas/peec/prompts_export/2.0.0.yaml
# Constraints are a BREAKING schema change, so they land in a major bump (design §4.3):
# under `@1` pinning a minor would reach every running consumer on its next resolve.
schema: peec.prompts_export
version: 2.0.0
kind: tabular
fields:
  - name: prompt
    type: string
    required: true
    min_length: 1
  - name: sentiment
    type: float
    required: true
    nullable: true
    minimum: -1.0
    maximum: 1.0
  - name: position
    type: int
    required: true
    nullable: true
    minimum: 1
  - name: is_owned
    type: int
    required: true
    nullable: true
    enum: [0, 1]
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_value_constraints.py`:

```python
# tests/test_value_constraints.py
from pathlib import Path

import pandas as pd
import pytest

from contract_core import ContractViolation, load_runtime

FIX = Path(__file__).parent / "fixtures"
SCHEMAS = FIX / "schemas"
CONTRACT = FIX / "consumer" / "contract_v2.yaml"


def _runtime():
    return load_runtime(CONTRACT, schema_paths=[SCHEMAS])


def _load(rt, frame):
    @rt.input("prompts")
    def load():
        return frame
    return load


def _good(**overrides):
    base = {"prompt": ["a", "b"], "sentiment": [0.5, -0.5],
            "position": [1, 2], "is_owned": [0, 1]}
    base.update(overrides)
    return pd.DataFrame(base)


def _violation(frame):
    with pytest.raises(ContractViolation) as ei:
        _load(_runtime(), frame)()
    return ei.value


def test_conforming_data_passes():
    # The true negative for the whole pipeline.
    assert _load(_runtime(), _good())() is not None


def test_out_of_range_value_hard_fails_with_count_and_samples():
    exc = _violation(_good(sentiment=[1.4, 0.5]))
    d = next(d for d in exc.diffs if d.field == "sentiment")
    assert d.problem == "value"
    assert d.constraint == "maximum=1.0"
    assert d.violating_rows == 1
    assert d.samples == ["1.4"]


def test_violating_rows_counts_every_offending_row():
    exc = _violation(_good(sentiment=[1.4, 2.7]))
    d = next(d for d in exc.diffs if d.field == "sentiment")
    assert d.violating_rows == 2


def test_samples_cap_at_three():
    frame = pd.DataFrame({"prompt": list("abcde"), "sentiment": [9.0] * 5,
                          "position": [1] * 5, "is_owned": [0] * 5})
    d = next(d for d in _violation(frame).diffs if d.field == "sentiment")
    assert d.violating_rows == 5
    assert len(d.samples) == 3


def test_enum_violation_is_reported():
    d = next(d for d in _violation(_good(is_owned=[0, 5])).diffs if d.field == "is_owned")
    assert d.problem == "value"
    assert d.constraint == "enum=[0, 1]"


def test_min_length_violation_is_reported():
    d = next(d for d in _violation(_good(prompt=["", "b"])).diffs if d.field == "prompt")
    assert d.constraint == "min_length=1"


def test_a_value_failure_is_not_reported_as_retyped():
    # Design §5.2: the whole classification story. Fails if the checks are built with
    # `name=` instead of `error=`.
    exc = _violation(_good(sentiment=[1.4, 0.5]))
    assert "retyped" not in [d.problem for d in exc.diffs]


def test_a_field_violating_two_constraints_reports_both():
    # Design §5.2.1: fails against the old last-wins de-dup, which kept one arbitrary diff.
    exc = _violation(_good(sentiment=[-9.0, 9.0]))
    got = sorted(d.constraint for d in exc.diffs if d.field == "sentiment")
    assert got == ["maximum=1.0", "minimum=-1.0"]


def test_wrong_dtype_reports_the_dtype_diff_and_drops_value_diffs():
    # Design §5.2.2: a value check on a str column raises, and pandera records the
    # TypeError as the failure case.
    exc = _violation(_good(sentiment=["not-a-number", "also-not"]))
    problems = {d.problem for d in exc.diffs if d.field == "sentiment"}
    assert problems == {"retyped"}


def test_no_typeerror_text_ever_reaches_samples():
    # The observable form of the rule above, and what fails if the drop rule runs after
    # aggregation instead of before it.
    exc = _violation(_good(sentiment=["not-a-number", "also-not"]))
    assert not any("TypeError" in s for d in exc.diffs for s in d.samples)


def test_nulls_do_not_trip_constraints():
    assert _load(_runtime(), _good(sentiment=[None, 0.5]))() is not None


def test_a_missing_column_still_reports_missing():
    frame = _good().drop(columns=["position"])
    d = next(d for d in _violation(frame).diffs if d.field == "position")
    assert d.problem == "missing"
    assert d.violating_rows is None
```

Create `tests/fixtures/consumer/contract_v2.yaml`:

```yaml
# tests/fixtures/consumer/contract_v2.yaml
# Pins the constrained 2.0.0 schema (design §4.3: constraints are a major bump).
system: demo-consumer-v2
version: 1.0.0
inputs:
  - name: prompts
    schema: peec.prompts_export@2.0.0
    source: {kind: file, format: csv}
    mode: enforce
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_value_constraints.py -q`
Expected: FAIL — `test_out_of_range_value_hard_fails...` reports `problem == "retyped"` with
`constraint is None`, because the classifier does not yet know the new check names.

- [ ] **Step 4: Implement**

In `src/contract_core/runtime.py`, **replace** the existing
`from contract_core.compile.pandera_compile import to_pandera` line with:

```python
from contract_core.compile.pandera_compile import (
    DTYPE_CHECK_PREFIX,
    VALUE_CHECK_NAMES,
    to_pandera,
)
```

Add these module-level helpers above `class ContractRuntime`:

```python
def _failure_field(row: Any) -> str | None:
    """The field a pandera failure case belongs to.

    For `column_in_dataframe` the field name is in `failure_case` and `column` is NaN, so a
    group-by on the raw `column` would put every missing column in one NaN bucket
    (design §5.2.1).
    """
    if str(row.get("check", "")) == "column_in_dataframe":
        return str(row.get("failure_case"))
    col = row.get("column")
    if col is None or (isinstance(col, float) and pd.isna(col)):
        return None
    return str(col)


def _constraint_label(check: str, declared: "FieldSpec | None") -> str:
    """`maximum=1.0` — what the operator needs to see, from the schema not the frame."""
    if declared is None:
        return check
    value = {"enum": declared.enum, "minimum": declared.minimum,
             "maximum": declared.maximum, "min_length": declared.min_length}[check]
    return f"{check}={value}"
```

Add `from contract_core.types import Field as FieldSpec` to the imports (aliased so it does not
collide with pandera/pydantic `Field` names a reader might expect).

Now replace everything in `_validate_tabular` **from the line `ps = to_pandera(resolved, strict=False)`
down to and including `diffs = list(seen.values())`** — that is, the `try`/`except` block, the
per-row append loop, and the whole `# de-dup by field` block — with:

```python
        ps = to_pandera(resolved, strict=False)
        cases: list[tuple[str, str, Any]] = []
        try:
            ps.validate(df, lazy=True)
        except pa.errors.SchemaErrors as err:
            for _, row in err.failure_cases.iterrows():
                field = _failure_field(row)
                if field is None:
                    continue
                cases.append((field, str(row.get("check", "")), row.get("failure_case")))

        # Drop rule FIRST, aggregation second (design §5.2.2). A value check against a
        # wrong dtype raises, and pandera records the TypeError as the failure case —
        # aggregating first would compute counts and samples off exception reprs.
        wrong_dtype = {f for f, c, _ in cases if c.startswith(DTYPE_CHECK_PREFIX)}
        cases = [(f, c, v) for f, c, v in cases
                 if not (f in wrong_dtype and c in VALUE_CHECK_NAMES)]

        groups: dict[tuple[str, str], list[Any]] = {}
        for field, check, value in cases:
            groups.setdefault((field, check), []).append(value)

        # Structural diffs collapse per field ("column missing" twice is noise); value
        # diffs do not collapse across constraints, because `minimum` and `maximum` on one
        # field are two distinct facts (design §5.2.1).
        structural: dict[str, FieldDiff] = {}
        diffs: list[FieldDiff] = []
        for (field, check), values in groups.items():
            declared = next((f for f in resolved.fields if f.name == field), None)
            expected = str(declared.type) if declared else "?"
            observed_dtype = str(df.dtypes.get(field, "absent"))
            if check in VALUE_CHECK_NAMES:
                diffs.append(FieldDiff(
                    field=field, expected=expected, observed=observed_dtype,
                    problem="value", constraint=_constraint_label(check, declared),
                    violating_rows=len(values),
                    samples=[str(v) for v in values[:3]],
                ))
            elif check == "column_in_dataframe":
                structural[field] = FieldDiff(field=field, expected=expected,
                                              observed="absent", problem="missing")
            elif check == "not_nullable":
                # a null-tolerance violation, not a type change: don't mislabel it
                # `retyped` with a (valid) dtype as observed.
                structural[field] = FieldDiff(field=field, expected=expected,
                                              observed="null", problem="nullable")
            else:
                structural[field] = FieldDiff(field=field, expected=expected,
                                              observed=observed_dtype, problem="retyped")
        diffs = [*structural.values(), *diffs]
```

Leave the `observed` dict construction above and the `if is_output:` extra-field block below
unchanged. Delete the now-unused `diffs: list[FieldDiff] = []` line that preceded `ps = ...`, since
the replacement declares `diffs` itself.

**`Problem` is now unused in `runtime.py`** — the replacement annotates nothing with it. Remove it
from the `from contract_core.errors import ...` line, or `ruff` will fail with `F401`. It stays
exported from `errors.py`, where Task 4 made it the single definition.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_value_constraints.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `pytest -q && ruff check . && mypy --strict`
Expected: all green. Existing runtime tests exercise structural diffs only, which keep collapsing per
field exactly as the old de-dup did.

- [ ] **Step 7: Anti-vacuity — prove the drop rule is load-bearing**

Temporarily delete the two `wrong_dtype` lines, then run:

Run: `pytest tests/test_value_constraints.py::test_no_typeerror_text_ever_reaches_samples -q`
Expected: **FAIL**, with a `TypeError(...)` string in `samples`. Restore the lines and confirm PASS.

- [ ] **Step 8: Commit**

```bash
git add src/contract_core/runtime.py tests/test_value_constraints.py \
        tests/fixtures/schemas/peec/prompts_export/2.0.0.yaml \
        tests/fixtures/consumer/contract_v2.yaml
git commit -m "feat: report value violations with a row count and samples"
```

---

### Task 6: Payload boundaries enforce constraints too

**Files:**
- Modify: `src/contract_core/runtime.py` (`_validate_payload`)
- Test: `tests/test_value_constraints.py`
- Test fixture: `tests/fixtures/schemas/aivx/report/2.0.0.yaml` (create)

**Interfaces:**
- Consumes: the JSON Schema keywords from Task 2 and `FieldDiff`'s fields from Task 4.

**Why:** `_validate_payload` branches on `required`, `type`, and `additionalProperties`. A `minimum`
or `enum` error matches none of them and is **dropped on the floor** — constraints would compile into
the payload schema and then do nothing (design §5.3).

- [ ] **Step 1: Create the fixture and write the failing test**

Create `tests/fixtures/schemas/aivx/report/2.0.0.yaml`:

```yaml
# tests/fixtures/schemas/aivx/report/2.0.0.yaml
schema: aivx.report
version: 2.0.0
kind: payload
fields:
  - name: slug
    type: string
    required: true
    min_length: 1
  - name: score
    type: float
    required: true
    nullable: true
    minimum: 0.0
    maximum: 1.0
  - name: tier
    type: string
    required: true
    enum: ["gold", "silver"]
```

Append to `tests/fixtures/consumer/contract_v2.yaml`:

```yaml
outputs:
  - name: report
    schema: aivx.report@2.0.0
    sink: {kind: file, format: json}
    mode: enforce
```

Append to `tests/test_value_constraints.py`:

```python
def _emit(rt, payload):
    @rt.output("report")
    def emit():
        return payload
    return emit


def _payload_violation(payload):
    with pytest.raises(ContractViolation) as ei:
        _emit(_runtime(), payload)()
    return ei.value


def test_payload_enum_violation_raises_rather_than_vanishing():
    # Design §5.3: a constraint that enforces on tabular boundaries and silently no-ops on
    # payload ones is worse than one that does not exist.
    exc = _payload_violation({"slug": "a", "score": 0.5, "tier": "bronze"})
    d = next(d for d in exc.diffs if d.field == "tier")
    assert d.problem == "value"
    assert d.constraint == 'enum=[\'gold\', \'silver\']'


def test_payload_bound_violation_raises():
    d = next(d for d in _payload_violation(
        {"slug": "a", "score": 9.0, "tier": "gold"}).diffs if d.field == "score")
    assert d.problem == "value"
    assert d.constraint == "maximum=1.0"


def test_payload_value_diff_has_no_row_count():
    # A payload is one document, not a frame: `violating_rows` is meaningless here.
    d = next(d for d in _payload_violation(
        {"slug": "a", "score": 9.0, "tier": "gold"}).diffs if d.field == "score")
    assert d.violating_rows is None
    assert d.samples == ["9.0"]


def test_conforming_payload_passes():
    assert _emit(_runtime(), {"slug": "a", "score": 0.5, "tier": "gold"})() is not None


def test_payload_null_in_a_nullable_field_does_not_trip_a_bound():
    assert _emit(_runtime(), {"slug": "a", "score": None, "tier": "gold"})() is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_value_constraints.py -k payload -q`
Expected: FAIL — `DID NOT RAISE ContractViolation`. The `jsonschema` error exists but matches no
branch, so no diff is appended.

- [ ] **Step 3: Implement**

In `_validate_payload`, add a branch before the existing `additionalProperties` branch:

```python
            elif err.validator in ("enum", "minimum", "maximum", "minLength"):
                # Design §5.3: without this branch a jsonschema value error matches no
                # branch and is dropped, so constraints compile into the payload schema
                # and then do nothing.
                field = str(err.path[-1]) if err.path else "?"
                declared = next((f for f in (resolved.fields or []) if f.name == field), None)
                key = {"minLength": "min_length"}.get(str(err.validator), str(err.validator))
                diffs.append(FieldDiff(
                    field=field, expected=str(declared.type) if declared else "?",
                    observed=type(err.instance).__name__, problem="value",
                    constraint=_constraint_label(key, declared),
                    violating_rows=None, samples=[str(err.instance)],
                ))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_value_constraints.py -q && pytest -q && mypy --strict`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/contract_core/runtime.py tests/test_value_constraints.py \
        tests/fixtures/schemas/aivx/report/2.0.0.yaml tests/fixtures/consumer/contract_v2.yaml
git commit -m "feat: enforce value constraints at payload boundaries"
```

---

### Task 7: ODCS export — bounds, enum-as-quality, and the null mapping

**Files:**
- Modify: `src/contract_core/compile/odcs.py`
- Test: `tests/test_compile_odcs.py`

**Interfaces:**
- Consumes: the `Field` constraints from Task 1.
- Produces: `_schema_block` emits `logicalTypeOptions` for bounds and a `quality` list for `enum` and
  null-tolerance. It **no longer emits `required`**.

**Three things that make this non-obvious (design §5.4):**

1. `logicalTypeOptions` is type-scoped through an `allOf`/`if`-`then` chain with
   `additionalProperties: false`. **No branch defines `enum`** — emitting it there makes
   `contract lint` fail on string/integer/number.
2. There is **no `boolean` branch**, so `logicalTypeOptions` on a boolean field validates
   *vacuously*. Never emit the key for a type with no branch.
3. ODCS `required` is documented as *null* semantics ("Indicates if the element may contain Null
   values"), not presence, and there is no `nullable` key. Emitting this project's presence flag
   there asserts something we do not mean (§5.4.2).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_compile_odcs.py`:

```python
from contract_core.compile.odcs import _schema_block, validate_odcs
from contract_core.schema import Schema


def _block(**field_kwargs):
    s = Schema(schema="t", version="1.0.0", kind="tabular",
               fields=[{"name": "f", **field_kwargs}])
    return _schema_block("b", s)["properties"][0]


def _doc(block_prop):
    return {"apiVersion": "v3.1.0", "kind": "DataContract", "id": "x", "name": "x",
            "version": "1.0.0", "status": "active",
            "schema": [{"name": "b", "physicalType": "table", "properties": [block_prop]}]}


def test_bounds_go_to_logical_type_options():
    p = _block(type="float", minimum=-1.0, maximum=1.0)
    assert p["logicalTypeOptions"] == {"minimum": -1.0, "maximum": 1.0}
    validate_odcs(_doc(p))


def test_min_length_goes_to_logical_type_options():
    p = _block(type="string", min_length=1)
    assert p["logicalTypeOptions"] == {"minLength": 1}
    validate_odcs(_doc(p))


def test_enum_goes_to_a_quality_rule_not_logical_type_options():
    # Design §5.4.1: ODCS has no `enum` option. Emitting one FAILS validation on
    # string/integer/number and passes vacuously on boolean.
    p = _block(type="int", enum=[0, 1])
    assert "logicalTypeOptions" not in p
    assert p["quality"] == [{"type": "library", "metric": "invalidValues",
                             "arguments": {"validValues": [0, 1]}, "mustBe": 0}]
    validate_odcs(_doc(p))


def test_a_nullable_enum_lists_null_among_the_valid_values():
    # The ODCS analogue of the JSON Schema fix (§5.1): `nullValues` and `invalidValues`
    # are separate metrics, so whether invalidValues counts nulls is engine-defined.
    p = _block(type="int", enum=[0, 1], nullable=True)
    assert p["quality"][0]["arguments"]["validValues"] == [0, 1, None]
    validate_odcs(_doc(p))


def test_non_nullable_field_emits_a_null_values_rule():
    p = _block(type="float", nullable=False)
    assert {"type": "library", "metric": "nullValues", "mustBe": 0} in p["quality"]
    validate_odcs(_doc(p))


def test_nullable_field_emits_no_null_values_rule():
    p = _block(type="float", nullable=True)
    assert not any(q.get("metric") == "nullValues" for q in p.get("quality", []))


def test_presence_is_not_exported_as_odcs_required():
    # ODCS `required` is null semantics, not presence (§5.4.2). Emitting our presence flag
    # there asserts the opposite of what the schema says about nulls.
    assert "required" not in _block(type="float", nullable=True)
    assert "required" not in _block(type="float", required=False)


def test_no_logical_type_options_for_a_type_with_no_odcs_branch():
    # Regression guard (§5.4, criterion 16): no authorable schema reaches this today,
    # because enum routes to quality and bounds are confined to int/float/string. It
    # catches a future re-route of enum into logicalTypeOptions, where boolean would pass
    # vacuously — {"totally_made_up": "x"} on a boolean field also validates.
    assert "logicalTypeOptions" not in _block(type="bool", enum=[True, False])


def test_a_schema_with_all_four_constraints_compiles_to_valid_odcs():
    s = Schema(schema="t", version="2.0.0", kind="tabular", fields=[
        {"name": "sentiment", "type": "float", "nullable": True,
         "minimum": -1.0, "maximum": 1.0},
        {"name": "rank", "type": "int", "minimum": 1},
        {"name": "brand", "type": "string", "min_length": 1},
        {"name": "is_owned", "type": "int", "enum": [0, 1]},
    ])
    block = _schema_block("prompts", s)
    validate_odcs({"apiVersion": "v3.1.0", "kind": "DataContract", "id": "x", "name": "x",
                   "version": "1.0.0", "status": "active", "schema": [block]})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_compile_odcs.py -q`
Expected: FAIL — `KeyError: 'logicalTypeOptions'`, and `test_presence_is_not_exported...` fails
because `required` is still emitted.

- [ ] **Step 3: Implement**

Replace `_ODCS_LOGICAL` and `_schema_block` in `src/contract_core/compile/odcs.py`:

```python
_ODCS_LOGICAL = {
    "string": "string", "int": "integer", "float": "number",
    "bool": "boolean", "date": "date", "datetime": "date",
}

# `logicalTypeOptions` is validated by an if/then chain keyed on logicalType, with
# additionalProperties: false on every branch — and there is NO boolean branch, so options
# on a boolean field validate vacuously. Only emit the key for a type that has a branch
# (design §5.4).
_TYPES_WITH_OPTIONS = {"string", "integer", "number", "date"}


def _logical_type_options(f: Field) -> dict[str, Any]:
    opts: dict[str, Any] = {}
    if f.minimum is not None:
        opts["minimum"] = f.minimum
    if f.maximum is not None:
        opts["maximum"] = f.maximum
    if f.min_length is not None:
        opts["minLength"] = f.min_length
    return opts


def _quality_rules(f: Field) -> list[dict[str, Any]]:
    """ODCS's home for an allowed-value set and for null tolerance (design §5.4.1/§5.4.2).

    `metric` is required by DataQualityLibrary, and the operator (`mustBe`) comes from a
    `oneOf` in DataQualityOperators — so `mustBe: 0` is load-bearing, not decoration.
    """
    rules: list[dict[str, Any]] = []
    if f.enum is not None:
        # Append None for a nullable field, exactly as the JSON Schema compiler does:
        # `nullValues` and `invalidValues` are separate ODCS metrics, so whether
        # invalidValues counts nulls is engine-defined.
        valid = [*f.enum, None] if f.nullable else list(f.enum)
        rules.append({"type": "library", "metric": "invalidValues",
                      "arguments": {"validValues": valid}, "mustBe": 0})
    if not f.nullable:
        # ODCS `required` is documented as null semantics, not presence, and its polarity
        # is ambiguous in the vendored text — so null tolerance is expressed here, where
        # the metric name says what it means (design §5.4.2).
        rules.append({"type": "library", "metric": "nullValues", "mustBe": 0})
    return rules


def _schema_block(name: str, resolved: Schema) -> dict[str, Any]:
    props: list[dict[str, Any]] = []
    if resolved.fields is not None:
        for f in resolved.fields:
            logical = _ODCS_LOGICAL[f.type]
            # `required` is deliberately NOT emitted: the ODCS slot is a null flag, not a
            # presence flag, so this project's `required` does not belong in it. Presence
            # has no unambiguous ODCS slot and is not exported (design §5.4.2).
            prop: dict[str, Any] = {"name": f.name, "logicalType": logical}
            opts = _logical_type_options(f)
            if opts and logical in _TYPES_WITH_OPTIONS:
                prop["logicalTypeOptions"] = opts
            rules = _quality_rules(f)
            if rules:
                prop["quality"] = rules
            props.append(prop)
    return {"name": name, "physicalType": "table", "properties": props}
```

Add `from contract_core.types import Field` to the imports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_compile_odcs.py -q && pytest -q && mypy --strict`
Expected: all green.

- [ ] **Step 5: Verify `contract lint` still passes end to end**

Run: `python -m contract_core.cli lint --contract tests/fixtures/contract_lintable.yaml --schemas tests/fixtures/schemas`
Expected: `OK: demo@1.0.0 — 1 boundaries resolved`

> If a quality rule is malformed while iterating, `jsonschema` reports
> `Unevaluated properties are not allowed ('arguments', 'metric' were unexpected)` — the
> `unevaluatedProperties` construct blames the **correct** keys. The real fault is elsewhere in the
> rule (usually a missing `mustBe`). Do not go looking at `metric`.

- [ ] **Step 6: Commit**

```bash
git add src/contract_core/compile/odcs.py tests/test_compile_odcs.py
git commit -m "feat: export value constraints and null tolerance to ODCS"
```

---

### Task 8: `lint` sees the schema files it is supposed to police

**Files:**
- Modify: `src/contract_core/cli.py`
- Test: `tests/test_cli.py`
- Test fixture: `tests/fixtures/schemas/peec/prompts_export/3.0.0.yaml` (create, deliberately broken)

**Interfaces:**
- Consumes: the load-time validation from Task 1.

**Why:** `lint` resolves only schemas *referenced by the given contract*, so a malformed new schema is
never loaded; and its `try/except` catches only `SchemaNotFound`, so a `ValidationError` escapes as a
traceback instead of the `LINT FAILED` report. In production the same error lands at **decoration
time** — module import — which is the crash class R9 removed (design §4.1.1).

- [ ] **Step 1: Create the broken fixture and write the failing tests**

Create `tests/fixtures/schemas/peec/prompts_export/3.0.0.yaml`:

```yaml
# tests/fixtures/schemas/peec/prompts_export/3.0.0.yaml
# DELIBERATELY INVALID: min_length on an int field. `lint` must report this even though no
# fixture contract references 3.0.0 (design §4.1.1).
schema: peec.prompts_export
version: 3.0.0
kind: tabular
fields:
  - name: position
    type: int
    required: true
    min_length: 1
```

Append to `tests/test_cli.py`:

```python
from click.testing import CliRunner

from contract_core.cli import lint


def test_lint_reports_a_malformed_constraint_in_an_unreferenced_schema():
    # 3.0.0 is referenced by no fixture contract. Design §4.1.1: lint must still see it,
    # or the authoring error surfaces at import time in production instead.
    result = CliRunner().invoke(lint, [
        "--contract", "tests/fixtures/contract_lintable.yaml",
        "--schemas", "tests/fixtures/schemas",
    ])
    assert result.exit_code == 1
    assert "LINT FAILED" in result.output
    assert "3.0.0" in result.output
    assert "min_length applies to string" in result.output


def test_lint_does_not_raise_a_traceback_on_a_malformed_schema():
    result = CliRunner().invoke(lint, [
        "--contract", "tests/fixtures/contract_lintable.yaml",
        "--schemas", "tests/fixtures/schemas",
    ])
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_lint_ignores_non_semver_files_like_latest_yaml():
    # `_parse_semver` returns None rather than raising SPECIFICALLY so the major-pin glob
    # skips latest.yaml and _template.yaml. Linting every *.yaml would turn a deliberate
    # accommodation into a failure (design §4.1.1).
    from contract_core.cli import _lintable_schema_files
    names = {p.name for p in _lintable_schema_files(["tests/fixtures/schemas"])}
    assert "latest.yaml" not in names
    assert "1.0.0.yaml" in names
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli.py -q`
Expected: FAIL — `exit_code == 0` (lint never loads 3.0.0), and `ImportError` for
`_lintable_schema_files`.

- [ ] **Step 3: Implement**

In `src/contract_core/cli.py`, add imports and the helper:

```python
from pathlib import Path

from pydantic import ValidationError

from contract_core.resolver import Resolver, SchemaNotFound, _parse_semver
from contract_core.schema import Schema


def _lintable_schema_files(schema_dirs: tuple[str, ...] | list[str]) -> list[Path]:
    """Every schema file the resolver would consider, and no others.

    Scoped to stems `_parse_semver` accepts: that helper returns None rather than raising
    so the major-pin glob skips strays like `latest.yaml` and `_template.yaml`. Linting
    every *.yaml would make a template file a lint error (design §4.1.1).
    """
    files: list[Path] = []
    for d in schema_dirs:
        for p in sorted(Path(d).rglob("*.yaml")):
            if _parse_semver(p.stem) is not None:
                files.append(p)
    return files
```

Then, in `lint`, insert this block immediately after `resolver = Resolver(list(schema_dirs))`:

```python
    malformed: list[str] = []
    for path in _lintable_schema_files(schema_dirs):
        try:
            Schema.from_yaml(path)
        except ValidationError as exc:
            first = exc.errors()[0]["msg"].removeprefix("Value error, ")
            malformed.append(f"{path}: {first}")
    if malformed:
        click.echo("LINT FAILED — malformed schemas:")
        for line in malformed:
            click.echo(f"  - {line}")
        sys.exit(1)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_cli.py -q && pytest -q && ruff check . && mypy --strict`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/contract_core/cli.py tests/test_cli.py \
        tests/fixtures/schemas/peec/prompts_export/3.0.0.yaml
git commit -m "fix: lint validates every resolver-visible schema, not only referenced ones"
```

---

### Task 9: Ship it — `v0.2.0`, changelog, and consumer docs

**Files:**
- Modify: `pyproject.toml` (line 7), `src/contract_core/__init__.py`, `CHANGELOG.md`,
  `docs/consuming-repo-setup.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Bump both version strings**

`pyproject.toml`: `version = "0.2.0"`. `src/contract_core/__init__.py`: `__version__ = "0.2.0"`.

These are the only two sites — `test_version_matches_pyproject` reads `pyproject.toml` directly.

- [ ] **Step 2: Run the version test**

Run: `pytest tests/test_smoke.py -q`
Expected: PASS.

- [ ] **Step 3: Write the changelog entry**

Insert into `CHANGELOG.md` immediately below `## [Unreleased]`:

```markdown
## [0.2.0] — unreleased, pending tag

### Added

- **Value constraints on schema fields** — `enum`, `minimum`, `maximum`, `min_length`.
  They compile to Pandera checks, JSON Schema keywords, and the ODCS export, and they
  hard-fail through the existing `observe`/`warn`/`enforce` ladder like structural drift.
  A violation reports the constraint, how many rows broke it, and up to three samples.
- Applicability is checked when the schema loads: `minimum`/`maximum` on `int`/`float`,
  `min_length` on `string`, `enum` on `string`/`int`/`bool` with values matching the
  declared type. `contract lint` now validates **every** schema file it can see, not only
  the ones the given contract references.

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

### Notes for consumers

- **Adding a constraint to a schema is a BREAKING change: bump the schema's MAJOR
  version.** A constraint can fail data that previously passed, and a `@1` pin resolves to
  the highest matching minor — so publishing constraints in a minor would reach every
  running consumer on its next resolve. Adopt a constraint-bearing major with the boundary
  in `observe`, read the event log, then promote to `enforce`.
- Constraints skip nulls. `nullable` remains the only null gate.
- `min_length: 1` rejects `""` but accepts `"  "`. A non-blank check needs `pattern`, which
  is not implemented yet.
```

- [ ] **Step 4: Document the constraints for consumers**

Append to `docs/consuming-repo-setup.md` §2, after the `load_runtime` example:

```markdown
### Value constraints

A schema field may declare `enum`, `minimum`, `maximum`, or `min_length`. They are enforced at the
boundary alongside presence and type, and a violation raises `ContractViolation` under `enforce`:

```python
except ContractViolation as exc:
    for d in exc.diffs:
        if d.problem == "value":
            print(d.field, d.constraint, d.violating_rows, d.samples)
```

Constraints apply only to non-null values — `nullable` is the only null gate. Adding one to a schema
is a **breaking** change and requires a major version bump.
```

- [ ] **Step 5: Run the full gate**

Run: `pytest -q && ruff check . && mypy --strict`
Expected: all green.

- [ ] **Step 6: Commit and open the PR**

```bash
git add pyproject.toml src/contract_core/__init__.py CHANGELOG.md docs/consuming-repo-setup.md
git commit -m "feat: release value constraints as v0.2.0"
git push -u origin feat/value-constraints
```

Open the PR against `dev`. **Do not tag `v0.2.0` here** — the tag is cut on `main`, per the release
procedure in `CONTRIBUTING.md`.

---

## Criteria coverage

Every criterion in §9 of the design maps to a task. Check this table before calling the plan done.

| Criterion | Task |
| --- | --- |
| 1 — violation hard-fails with count and samples | 5 |
| 2 — conforming data passes (true negative) | 3, 5 |
| 3 — nulls do not trip constraints | 3, 5 |
| 4 — `nullable` + `enum` accepts null | 2 |
| 5 — value failure is not `retyped` | 5 |
| 6 — two constraints on one field report both | 3, 5 |
| 7 — dtype failure suppresses value diffs | 5 |
| 8 — `violating_rows`/`samples` typed | 4, 5 |
| 9 — `minimum` on a string fails at load | 1 |
| 10 — enum type mismatch fails at load | 1 |
| 11 — `lint` reports a malformed unreferenced schema | 8 |
| 12 — payload enum violation raises | 6 |
| 13 — JSON Schema carries the keywords | 2 |
| 14 — full four-constraint ODCS document validates | 7 |
| 15 — `enum` is a quality rule, not a logical-type option | 7 |
| 16 — no options for a branch-less type *(regression guard)* | 7 |
| 17 — no `TypeError` text in samples | 5 |
| 18 — no ODCS assertion contradicting `nullable` | 7 |
| 19 — `nullable: false` emits a `nullValues` rule | 7 |
| 20 — nullable enum lists `null` in `validValues` | 7 |
