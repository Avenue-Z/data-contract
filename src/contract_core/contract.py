# src/contract_core/contract.py
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from contract_core.types import (
    CURRENT_FORMAT_VERSION,
    load_yaml_model,
    reject_non_current_format_version,
)

Mode = Literal["observe", "warn", "enforce"]
Direction = Literal["raw", "input", "output"]


class BoundarySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    # The schema ref ("platform.name@version"). Authored under the YAML key `schema`; the Python
    # attribute is `schema_ref` (via alias) so it does NOT shadow the deprecated `BaseModel.schema`
    # (§15 item 5).
    schema_ref: str = Field(alias="schema")
    mode: Mode = "enforce"
    source: dict[str, Any] | None = None
    sink: dict[str, Any] | None = None


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: str = CURRENT_FORMAT_VERSION
    system: str
    version: str
    raw: list[BoundarySpec] = []
    inputs: list[BoundarySpec] = []
    outputs: list[BoundarySpec] = []

    _only_current_format = field_validator("format_version")(reject_non_current_format_version)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Contract":
        return load_yaml_model(cls, path)
