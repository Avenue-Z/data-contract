# src/contract_core/types.py
import math
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from contract_core.errors import ContractFormatError

FieldType = Literal["string", "int", "float", "bool", "date", "datetime"]

# Design §4.1. Narrow on purpose: a constraint is allowed only where all three compile
# targets agree what it means.
_BOUND_TYPES = {"int", "float"}
_ENUM_TYPES = {"string", "int", "bool"}

# Design §4.5. Two names, two jobs. Both "v1" today; they diverge the moment v2 exists.
READABLE_FORMAT_VERSIONS: frozenset[str] = frozenset({"v1"})  # the dispatcher's input set
CURRENT_FORMAT_VERSION: str = "v1"                            # the model's only legal value


def normalize_format_version(data: dict[str, Any], path: str) -> dict[str, Any]:
    """Carry a raw authored dict forward to the current format, or refuse it (§4.5).

    A missing stamp means v1: a file with no version predates versioning. An unreadable
    version is refused here, on the raw dict, before the model — the dispatcher half of the
    two rejecting sites in §4.5. There is no upcast chain today (§10); the key is rewritten
    to current so the "model only sees the current format" invariant is structural, not a
    coincidence of v1 == current.
    """
    found = data.get("format_version", "v1")
    if not isinstance(found, str) or found not in READABLE_FORMAT_VERSIONS:
        raise ContractFormatError.unreadable_version(
            path=path, found=found, supported=READABLE_FORMAT_VERSIONS)
    return {**data, "format_version": CURRENT_FORMAT_VERSION}


def load_yaml_model[ModelT: BaseModel](model: type[ModelT], path: str | Path) -> ModelT:
    """Read an authored YAML file into `model`, wrapping format failures (design §5.1).

    OSError from read_text leaks intentionally — an unreadable file is not a malformed one.
    """
    p = Path(path)
    text = p.read_text()
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ContractFormatError(
            path=str(p),
            errors=[("<file>", f"invalid YAML — {' '.join(str(exc).split())}")],
            hint=None,
        ) from exc
    data = normalize_format_version(raw, str(p)) if isinstance(raw, dict) else raw
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ContractFormatError.from_validation_error(str(p), exc) from exc


def _value_matches_type(value: Any, declared: str) -> bool:
    # bool before int: isinstance(True, int) is True, so an unguarded int check would
    # accept `enum: [true, false]` on an int field.
    if declared == "bool":
        return isinstance(value, bool)
    if declared == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, str)


class Field(BaseModel):
    model_config = ConfigDict(extra="forbid")

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

    @field_validator("minimum", "maximum", mode="before")
    @classmethod
    def _bound_is_not_a_bool(cls, v: Any, info: ValidationInfo) -> Any:
        # Must run `mode="before"`: `int | float` smart-unions True to 1, so by the time
        # the model validator sees it, `minimum: true` is indistinguishable from
        # `minimum: 1`. Same trap `_value_matches_type` already refuses for enum — one
        # guarded and one not, in one file, is worse than neither.
        if isinstance(v, bool):
            raise ValueError(
                f"field {info.data.get('name')!r}: "
                f"{info.field_name} must be a number, not a bool"
            )
        return v

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
        if self.type == "int":
            # A fractional bound on an integer column means the next whole number, which
            # is not what it appears to say. An integral float (`1.0`) is unambiguous, so
            # it is accepted — but normalised to int, or it renders "minimum=1.0" on an
            # integer column and reintroduces the decimal by another route.
            for slot in ("minimum", "maximum"):
                bound = getattr(self, slot)
                if bound is None:
                    continue
                if bound != int(bound):
                    raise ValueError(
                        f"field {self.name!r}: {slot} on an int field must be a whole "
                        f"number, got {bound}"
                    )
                setattr(self, slot, int(bound))
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
            if self.minimum is not None or self.maximum is not None:
                # Reachable only for `int`: bounds require int/float and enum requires
                # string/int/bool. An enum disjoint from its bounds is the empty-interval
                # error wearing a different hat — the admissible set is empty, so every
                # non-null row fails while looking like a data problem. A PARTIAL overlap
                # is legitimate narrowing, not an error.
                lo = self.minimum if self.minimum is not None else -math.inf
                hi = self.maximum if self.maximum is not None else math.inf
                if not any(lo <= v <= hi for v in self.enum):
                    raise ValueError(
                        f"field {self.name!r}: no enum value satisfies the declared "
                        f"bounds — enum {self.enum!r} against [{lo}, {hi}]"
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
