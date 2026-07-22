# src/contract_core/types.py
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
    # `int | float`, not `float`: a plain `float` coerces `minimum: 1` on an int field to
    # 1.0, and that mangling reaches the operator message, the JSON Schema `minimum`
    # keyword and ODCS `logicalTypeOptions` alike. Pydantic's smart union preserves the
    # authored type, so an int bound stays an int.
    minimum: int | float | None = None
    maximum: int | float | None = None
    min_length: int | None = None

    @model_validator(mode="after")
    def _constraints_match_the_declared_type(self) -> "Field":
        if (self.minimum is not None or self.maximum is not None) \
                and self.type not in _BOUND_TYPES:
            raise ValueError(
                f"field {self.name!r}: minimum/maximum apply to int/float, not {self.type!r}"
            )
        if self.minimum is not None and self.maximum is not None \
                and self.minimum > self.maximum:
            # An empty interval is the same authoring error as an empty enum: it admits
            # no value, so it fails every non-null row while looking like a data problem.
            raise ValueError(
                f"field {self.name!r}: minimum {self.minimum} exceeds maximum {self.maximum}"
            )
        if self.min_length is not None and self.type != "string":
            raise ValueError(
                f"field {self.name!r}: min_length applies to string, not {self.type!r}"
            )
        if self.min_length is not None and self.min_length < 1:
            # 0 and negatives admit every string: a no-op that reads as a constraint.
            raise ValueError(
                f"field {self.name!r}: min_length must be >= 1, got {self.min_length}"
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
