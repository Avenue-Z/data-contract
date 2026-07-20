# src/contract_core/contract.py
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

Mode = Literal["observe", "warn", "enforce"]
Direction = Literal["raw", "input", "output"]


class BoundarySpec(BaseModel):
    name: str
    # `schema` is a ref ("platform.name@version"); matches the YAML key, shadows BaseModel.schema.
    schema: str  # type: ignore[assignment]
    mode: Mode = "enforce"
    source: dict[str, Any] | None = None
    sink: dict[str, Any] | None = None


class Contract(BaseModel):
    system: str
    version: str
    raw: list[BoundarySpec] = []
    inputs: list[BoundarySpec] = []
    outputs: list[BoundarySpec] = []

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Contract":
        data = yaml.safe_load(Path(path).read_text())
        return cls.model_validate(data)
