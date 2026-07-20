# src/contract_core/types.py
from typing import Any, Literal

from pydantic import BaseModel

FieldType = Literal["string", "int", "float", "bool", "date", "datetime"]


class Field(BaseModel):
    name: str
    type: FieldType
    required: bool = True
    nullable: bool = False


PANDAS_DTYPE: dict[str, str] = {
    "string": "str",
    "int": "Int64",
    "float": "float64",
    "bool": "boolean",
    "date": "datetime64[ns]",
    "datetime": "datetime64[ns]",
}

JSON_SCHEMA_TYPE: dict[str, dict[str, Any]] = {
    "string": {"type": "string"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "bool": {"type": "boolean"},
    "date": {"type": "string", "format": "date"},
    "datetime": {"type": "string", "format": "date-time"},
}
