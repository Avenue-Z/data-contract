# src/contract_core/schema.py
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from contract_core.types import CURRENT_FORMAT_VERSION, Field, load_yaml_model


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: str = CURRENT_FORMAT_VERSION
    # `schema` intentionally matches the YAML key; it shadows BaseModel.schema (deprecated).
    schema: str  # type: ignore[assignment]
    version: str
    kind: Literal["tabular", "payload"]
    fields: list[Field] | None = None
    json_schema: dict[str, Any] | None = None

    @property
    def ref(self) -> str:
        return f"{self.schema}@{self.version}"

    @field_validator("format_version")
    @classmethod
    def _only_current_format(cls, v: str) -> str:
        # Through from_yaml the dispatcher has already normalized to current; this fires on
        # direct construction (§4.5 pt 2) and catches an upcast that forgot to rewrite the key.
        if v != CURRENT_FORMAT_VERSION:
            raise ValueError(
                f"format_version {v!r} is not the current format {CURRENT_FORMAT_VERSION!r}")
        return v

    @model_validator(mode="after")
    def _exactly_one_body(self) -> "Schema":
        if (self.fields is None) == (self.json_schema is None):
            raise ValueError("schema must set exactly one of `fields` or `json_schema`")
        if self.json_schema is not None and self.kind != "payload":
            raise ValueError("`json_schema` is only allowed when kind == 'payload'")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Schema":
        return load_yaml_model(cls, path)
