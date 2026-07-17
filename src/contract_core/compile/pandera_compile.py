# src/contract_core/compile/pandera_compile.py
import pandera.pandas as pa

from contract_core.schema import Schema
from contract_core.types import PANDAS_DTYPE


def to_pandera(schema: Schema, *, strict: bool) -> pa.DataFrameSchema:
    if schema.kind != "tabular":
        raise ValueError(f"to_pandera requires kind 'tabular', got {schema.kind!r}")
    columns = {
        f.name: pa.Column(
            PANDAS_DTYPE[f.type],
            nullable=f.nullable,
            required=f.required,
            coerce=False,  # load-bearing: coercion would hide type drift (criterion #1)
        )
        for f in schema.fields
    }
    return pa.DataFrameSchema(columns, strict=strict)
