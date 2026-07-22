# src/contract_core/errors.py
from typing import Literal

from pydantic import BaseModel, Field

# The single definition. `runtime.py` imports this rather than restating it: two copies
# of the same Literal can drift, and adding a fifth variant is when that starts to matter
# (design §7).
Problem = Literal["missing", "retyped", "nullable", "extra", "value"]


class FieldDiff(BaseModel):
    field: str
    expected: str
    observed: str
    problem: Problem
    # Value-violation detail (design §6.2). None / empty on every structural diff.
    # `expected` and `observed` keep their existing meanings — the declared type and the
    # observed dtype/state — so a consumer reading them does not break.
    constraint: str | None = None
    violating_rows: int | None = None
    samples: list[str] = Field(default_factory=list)


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
            head = f"{self.schema_ref} at {self.direction} '{self.boundary}': "
            if d.problem == "value":
                detail = f"value field '{d.field}' violates {d.constraint}"
                if d.violating_rows is not None:
                    detail += f" — {d.violating_rows} rows"
                if d.samples:
                    detail += f" (e.g. {', '.join(d.samples)})"
                lines.append(head + detail)
            else:
                lines.append(
                    head + f"{d.problem} field '{d.field}' "
                    f"expected {d.expected}, observed {d.observed}"
                )
        return "\n".join(lines)
