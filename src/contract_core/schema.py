# src/contract_core/schema.py
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, model_validator

from contract_core.types import Field


class Schema(BaseModel):
    # `schema` intentionally matches the YAML key; it shadows BaseModel.schema (deprecated).
    schema: str  # type: ignore[assignment]
    version: str
    kind: Literal["tabular", "payload"]
    fields: list[Field] | None = None
    json_schema: dict[str, Any] | None = None

    @property
    def ref(self) -> str:
        return f"{self.schema}@{self.version}"

    @model_validator(mode="after")
    def _exactly_one_body(self) -> "Schema":
        if (self.fields is None) == (self.json_schema is None):
            raise ValueError("schema must set exactly one of `fields` or `json_schema`")
        if self.json_schema is not None and self.kind != "payload":
            raise ValueError("`json_schema` is only allowed when kind == 'payload'")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Schema":
        data = yaml.safe_load(Path(path).read_text())
        return cls.model_validate(data)
