# tests/test_types.py
import pytest
from pydantic import ValidationError

from contract_core.types import JSON_SCHEMA_TYPE, PANDAS_DTYPE, Field


def test_field_defaults_required_not_nullable():
    f = Field(name="order_id", type="string")
    assert f.required is True
    assert f.nullable is False


def test_field_rejects_unknown_type():
    with pytest.raises(ValueError):
        Field(name="x", type="decimal")


def test_type_maps_cover_all_field_types():
    kinds = {"string", "int", "float", "bool", "date", "datetime"}
    assert set(PANDAS_DTYPE) == kinds
    assert set(JSON_SCHEMA_TYPE) == kinds
    assert JSON_SCHEMA_TYPE["datetime"] == {"type": "string", "format": "date-time"}


# ---- value constraints (design §4.1) ----

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


# ---- satisfiability, not just applicability ----

def test_an_empty_interval_is_rejected():
    # Same class of error as an empty enum, and the same reasoning: a constraint that
    # cannot admit any value fails 100% of rows while presenting to the operator as a
    # data problem. That is the failure this validator exists to prevent.
    with pytest.raises(ValidationError, match="minimum 5.* exceeds maximum 1"):
        Field(name="position", type="int", minimum=5, maximum=1)


def test_a_degenerate_interval_is_allowed():
    # minimum == maximum admits exactly one value. Narrow, but satisfiable and meaningful.
    f = Field(name="k", type="int", minimum=3, maximum=3)
    assert (f.minimum, f.maximum) == (3, 3)


def test_min_length_below_one_is_rejected():
    # `min_length: 0` and `min_length: -1` admit every string, so they are no-ops that
    # read as constraints — the author meant something and got nothing.
    for bad in (0, -1):
        with pytest.raises(ValidationError, match="min_length must be >= 1"):
            Field(name="brand", type="string", min_length=bad)


def test_an_int_bound_stays_an_int():
    # `float` would store 1.0 and render "minimum=1.0" on an integer column, to the
    # operator, to JSON Schema and to ODCS alike.
    f = Field(name="position", type="int", minimum=1)
    assert f.minimum == 1
    assert isinstance(f.minimum, int)


def test_a_float_bound_stays_a_float():
    f = Field(name="sentiment", type="float", minimum=-1.0)
    assert isinstance(f.minimum, float)


def test_a_bool_is_not_a_number_for_bound_purposes():
    # The same trap `_value_matches_type` guards for enum, on the other constraint:
    # `int | float` smart-unions True to 1, so `minimum: true` silently means `minimum: 1`.
    # One guarded and one not, in one file, is worse than neither.
    with pytest.raises(ValidationError, match="minimum must be a number, not a bool"):
        Field(name="rank", type="int", minimum=True)
    with pytest.raises(ValidationError, match="maximum must be a number, not a bool"):
        Field(name="rank", type="int", maximum=False)


def test_numeric_bounds_still_accept_zero_and_negatives():
    # The bool guard must key on type, not falsiness: 0 and 0.0 are legitimate bounds.
    assert Field(name="a", type="int", minimum=0).minimum == 0
    assert Field(name="b", type="float", minimum=0.0, maximum=0.0).maximum == 0.0
    assert Field(name="c", type="float", minimum=-2.5).minimum == -2.5
