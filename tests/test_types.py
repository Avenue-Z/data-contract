# tests/test_types.py
import pytest
from contract_core.types import Field, PANDAS_DTYPE, JSON_SCHEMA_TYPE


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
