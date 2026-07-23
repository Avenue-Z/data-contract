# src/contract_core/contract.py
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from contract_core.types import CURRENT_FORMAT_VERSION, load_yaml_model

Mode = Literal["observe", "warn", "enforce"]
Direction = Literal["raw", "input", "output"]


class BoundarySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    # `schema` is a ref ("platform.name@version"); matches the YAML key, shadows BaseModel.schema.
    schema: str  # type: ignore[assignment]
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

    @field_validator("format_version")
    @classmethod
    def _only_current_format(cls, v: str) -> str:
        if v != CURRENT_FORMAT_VERSION:
            raise ValueError(
                f"format_version {v!r} is not the current format {CURRENT_FORMAT_VERSION!r}")
        return v

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Contract":
        return load_yaml_model(cls, path)
