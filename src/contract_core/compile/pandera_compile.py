# src/contract_core/compile/pandera_compile.py
import pandera.pandas as pa

from contract_core.families import dtype_satisfies
from contract_core.schema import Schema


def _family_check(field_type: str) -> pa.Check:
    """A non-mutating check that the column's physical dtype satisfies `field_type`.

    Replaces exact-dtype equality (R8): matches on logical type families so an
    inferred-but-equivalent dtype (int64 for a float, float64 for a nullable int,
    object vs str) passes, while a genuine type change (a stringified number, a
    real decimal where an int was declared) still fails. `coerce=False` stays the
    default so nothing is mutated to hide drift (success criterion #1).
    """
    return pa.Check(
        lambda s: dtype_satisfies(field_type, s),
        name=f"dtype_family:{field_type}",
        error=f"column dtype does not satisfy declared type {field_type!r}",
    )


def to_pandera(schema: Schema, *, strict: bool) -> pa.DataFrameSchema:
    if schema.kind != "tabular":
        raise ValueError(f"to_pandera requires kind 'tabular', got {schema.kind!r}")
    assert schema.fields is not None  # a tabular schema always has fields (Schema validator)
    columns = {
        f.name: pa.Column(
            dtype=None,  # dtype equality replaced by the family check below (R8)
            nullable=f.nullable,
            required=f.required,
            checks=_family_check(f.type),
            coerce=False,  # load-bearing: coercion would hide type drift (criterion #1)
        )
        for f in schema.fields
    }
    return pa.DataFrameSchema(columns, strict=strict)
