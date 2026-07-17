# tests/test_compile_pandera.py
import pandas as pd
import pandera.pandas as pa
import pytest
from contract_core.compile.pandera_compile import to_pandera
from contract_core.schema import Schema


def _schema():
    return Schema.model_validate({
        "schema": "peec.prompts_export", "version": "1.0.0", "kind": "tabular",
        "fields": [
            {"name": "prompt", "type": "string", "required": True},
            {"name": "position", "type": "int", "required": True, "nullable": True},
        ],
    })


def _good_df():
    return pd.DataFrame({"prompt": ["a"], "position": pd.array([1], dtype="Int64")})


def test_good_data_passes():
    ps = to_pandera(_schema(), strict=False)
    ps.validate(_good_df())  # must not raise


def test_open_schema_allows_extra_columns():
    ps = to_pandera(_schema(), strict=False)
    df = _good_df()
    df["extra"] = [9]
    ps.validate(df)  # must not raise — extra column allowed when open


def test_missing_required_column_fails():
    ps = to_pandera(_schema(), strict=False)
    df = _good_df().drop(columns=["position"])  # missing `position`
    with pytest.raises(pa.errors.SchemaError):
        ps.validate(df)


def test_wrong_dtype_fails_not_coerced():
    # criterion #1 lives or dies here: a stringified int MUST fail, not coerce.
    ps = to_pandera(_schema(), strict=False)
    df = _good_df()
    df["position"] = df["position"].astype(str)  # object, not Int64
    with pytest.raises(pa.errors.SchemaError):
        ps.validate(df)


def test_rejects_non_tabular():
    s = Schema.model_validate({"schema": "x.y", "version": "1.0.0", "kind": "payload",
                               "json_schema": {"type": "object"}})
    with pytest.raises(ValueError):
        to_pandera(s, strict=False)
