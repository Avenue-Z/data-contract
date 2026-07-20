# tests/test_families.py
import numpy as np
import pandas as pd
import pytest

from contract_core.families import dtype_satisfies

# ---- numeric: int64 satisfies float (the headline R8 false-positive) ----

def test_int64_satisfies_float():
    assert dtype_satisfies("float", pd.Series([1, 2], dtype="int64"))


def test_nullable_int_satisfies_int():
    assert dtype_satisfies("int", pd.Series(pd.array([1, 2], dtype="Int64")))


def test_plain_int64_satisfies_int():
    assert dtype_satisfies("int", pd.Series([1, 2], dtype="int64"))


def test_whole_number_float_satisfies_int():
    # nullable int read from a CSV upcasts to float64 on the NaN -> must pass
    assert dtype_satisfies("int", pd.Series([1.0, 2.0, np.nan]))


def test_real_decimal_float_does_not_satisfy_int():
    # a genuine float-where-int-declared narrowing drift -> must fail
    assert not dtype_satisfies("int", pd.Series([1.5, 2.0]))


def test_any_numeric_satisfies_float():
    assert dtype_satisfies("float", pd.Series(pd.array([1, 2], dtype="Int64")))
    assert dtype_satisfies("float", pd.Series([1.5], dtype="float64"))


# ---- criterion #1: stringified numbers must still fail ----

def test_stringified_int_does_not_satisfy_int():
    assert not dtype_satisfies("int", pd.Series(["1", "2"]))


def test_stringified_float_does_not_satisfy_float():
    assert not dtype_satisfies("float", pd.Series(["1.0", "2.0"]))


# ---- string family: object and pandas string dtype both pass (pandas 2<->3) ----

def test_object_strings_satisfy_string():
    assert dtype_satisfies("string", pd.Series(["a", "b"], dtype="object"))


def test_pandas_string_dtype_satisfies_string():
    assert dtype_satisfies("string", pd.Series(["a", "b"], dtype="string"))


def test_numeric_does_not_satisfy_string():
    assert not dtype_satisfies("string", pd.Series([1, 2], dtype="int64"))


def test_object_column_of_ints_does_not_satisfy_string():
    # object dtype is not a content guarantee (post-concat/apply drift); a column
    # declared `string` that actually holds ints must fail, not pass on dtype alone.
    assert not dtype_satisfies("string", pd.Series([1, 2, 3], dtype=object))


def test_object_column_of_non_str_objects_does_not_satisfy_string():
    assert not dtype_satisfies("string", pd.Series([{"a": 1}], dtype=object))


def test_object_column_of_mixed_str_and_int_does_not_satisfy_string():
    assert not dtype_satisfies("string", pd.Series(["a", 2], dtype=object))


# ---- bool is its own family (not numeric) ----

def test_bool_satisfies_bool():
    assert dtype_satisfies("bool", pd.Series([True, False]))
    assert dtype_satisfies("bool", pd.Series(pd.array([True, False], dtype="boolean")))


def test_bool_does_not_satisfy_int():
    # numpy reports bool as numeric; an int->bool drift must be caught
    assert not dtype_satisfies("int", pd.Series([True, False]))


def test_int_does_not_satisfy_bool():
    assert not dtype_satisfies("bool", pd.Series([1, 0], dtype="int64"))


# ---- temporal ----

def test_datetime_satisfies_datetime_and_date():
    s = pd.to_datetime(pd.Series(["2026-01-01"]))
    assert dtype_satisfies("datetime", s)
    assert dtype_satisfies("date", s)


def test_string_does_not_satisfy_datetime():
    assert not dtype_satisfies("datetime", pd.Series(["2026-01-01"], dtype="object"))


# ---- all-null escape: dtype uninformative, nullability enforced separately ----

@pytest.mark.parametrize("declared", ["int", "float", "string", "bool", "datetime"])
def test_all_null_object_satisfies_any_type(declared):
    assert dtype_satisfies(declared, pd.Series([None, None], dtype="object"))


@pytest.mark.parametrize("declared", ["int", "string", "bool"])
def test_all_null_float_satisfies_any_type(declared):
    assert dtype_satisfies(declared, pd.Series([np.nan, np.nan]))
