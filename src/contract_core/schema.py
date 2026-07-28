# src/contract_core/schema.py
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from pydantic import Field as PydanticField  # `Field` below is contract_core.types.Field

from contract_core.types import (
    CURRENT_FORMAT_VERSION,
    Field,
    load_yaml_model,
    reject_non_current_format_version,
)


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: str = CURRENT_FORMAT_VERSION
    # The dotted schema identity ("platform.name"). Authored under the YAML key `schema`; the Python
    # attribute is `schema_name` (via alias) so it does NOT shadow the deprecated `BaseModel.schema`
    # — that shadow warned on every import/run, visible to every CLI consumer (§15 item 5).
    schema_name: str = PydanticField(alias="schema")
    version: str
    kind: Literal["tabular", "payload"]
    fields: list[Field] | None = None
    json_schema: dict[str, Any] | None = None

    @property
    def ref(self) -> str:
        return f"{self.schema_name}@{self.version}"

    _only_current_format = field_validator("format_version")(reject_non_current_format_version)

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
