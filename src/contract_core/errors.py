# src/contract_core/errors.py
from typing import Literal

from pydantic import BaseModel


class FieldDiff(BaseModel):
    field: str
    expected: str
    observed: str
    problem: Literal["missing", "retyped", "extra"]


class ContractViolation(Exception):
    def __init__(self, *, boundary: str, schema_ref: str, direction: str,
                 diffs: list[FieldDiff]) -> None:
        self.boundary = boundary
        self.schema_ref = schema_ref
        self.direction = direction
        self.diffs = diffs
        super().__init__(self._render())

    def _render(self) -> str:
        lines = []
        for d in self.diffs:
            lines.append(
                f"{self.schema_ref} at {self.direction} '{self.boundary}': "
                f"{d.problem} field '{d.field}' expected {d.expected}, observed {d.observed}"
            )
        return "\n".join(lines)
