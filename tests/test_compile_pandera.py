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


# ---- R8: physical-dtype families, not exact-dtype equality ----

def _numeric_schema():
    return Schema.model_validate({
        "schema": "x.y", "version": "1.0.0", "kind": "tabular",
        "fields": [
            {"name": "amount", "type": "float", "required": True},
            {"name": "count", "type": "int", "required": True, "nullable": True},
        ],
    })


def test_int64_column_satisfies_declared_float():
    # R8 headline: a client CSV with no decimals infers int64 for a float field.
    ps = to_pandera(_numeric_schema(), strict=False)
    df = pd.DataFrame({"amount": pd.array([1, 2], dtype="int64"),
                       "count": pd.array([1, 2], dtype="Int64")})
    ps.validate(df)  # must not raise


def test_nullable_int_read_as_float64_satisfies_declared_int():
    # a nullable int read from CSV upcasts to float64 on its NaN.
    ps = to_pandera(_numeric_schema(), strict=False)
    df = pd.DataFrame({"amount": [1.0, 2.0], "count": [1.0, 2.0]})
    ps.validate(df)  # must not raise


def test_real_decimal_where_int_declared_still_fails():
    ps = to_pandera(_numeric_schema(), strict=False)
    df = pd.DataFrame({"amount": [1.0], "count": [1.5]})  # count is a real decimal
    with pytest.raises(pa.errors.SchemaError):
        ps.validate(df)


def test_stringified_number_still_fails_for_float_and_int():
    # criterion #1 preserved: object-of-strings is a genuine type change.
    ps = to_pandera(_numeric_schema(), strict=False)
    df = pd.DataFrame({"amount": ["1.0"], "count": ["1"]})
    with pytest.raises(pa.errors.SchemaError):
        ps.validate(df)


def _string_schema():
    return Schema.model_validate({
        "schema": "x.y", "version": "1.0.0", "kind": "tabular",
        "fields": [{"name": "label", "type": "string", "required": True}],
    })


def test_object_and_pandas_string_dtype_both_satisfy_string():
    ps = to_pandera(_string_schema(), strict=False)
    ps.validate(pd.DataFrame({"label": pd.array(["a"], dtype="object")}))
    ps.validate(pd.DataFrame({"label": pd.array(["a"], dtype="string")}))


def _nullable_schema(*, nullable: bool):
    return Schema.model_validate({
        "schema": "x.y", "version": "1.0.0", "kind": "tabular",
        "fields": [{"name": "n", "type": "int", "required": True, "nullable": nullable}],
    })


def test_all_null_column_passes_when_nullable():
    ps = to_pandera(_nullable_schema(nullable=True), strict=False)
    ps.validate(pd.DataFrame({"n": pd.array([None, None], dtype="object")}))


def test_all_null_column_fails_when_not_nullable():
    ps = to_pandera(_nullable_schema(nullable=False), strict=False)
    with pytest.raises(pa.errors.SchemaError):
        ps.validate(pd.DataFrame({"n": pd.array([None, None], dtype="object")}))
