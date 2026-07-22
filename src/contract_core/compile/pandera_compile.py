# src/contract_core/compile/pandera_compile.py
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
