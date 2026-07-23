# src/contract_core/errors.py
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

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


_UPGRADE_HINT = (
    "The file was likely authored against a newer contract-core. Upgrade the pin, or "
    "author the file against {ver}. See CHANGELOG.md."
)


def _reader_version() -> str:
    try:
        return _pkg_version("contract-core")
    except PackageNotFoundError:  # a source checkout with no install
        return "unknown"


class ContractFormatError(ValueError):
    """An authored file cannot be read as the current format (design R10, §5).

    Raised ONLY at the `from_yaml` boundary (§5.1). Subclasses ValueError so a consumer
    catching ValueError around `load_runtime` keeps working; is deliberately NOT a
    `ContractViolation`, which signals bad *data*, not a malformed *artifact* (§5.3).

    `.path` / `.errors` / `.hint` are a frozen attribute surface (§5.2.1): consumers read
    them to build custom handling, so renaming one is a breaking change.
    """

    def __init__(self, *, path: str, errors: list[tuple[str, str]], hint: str | None) -> None:
        self.path = path
        self.errors = errors
        self.hint = hint
        super().__init__(self._render())

    @classmethod
    def from_validation_error(cls, path: str, exc: ValidationError) -> "ContractFormatError":
        # Every error, not just the first (§5.2.1). `msg`'s "Value error, " prefix is
        # pydantic presentation over a raised ValueError; strip it, as `cli` already did.
        errors = [
            (".".join(str(p) for p in e["loc"]),
             str(e["msg"]).removeprefix("Value error, "))
            for e in exc.errors()
        ]
        unknown_keys = any(e["type"] == "extra_forbidden" for e in exc.errors())
        hint = _UPGRADE_HINT.format(ver=_reader_version()) if unknown_keys else None
        return cls(path=path, errors=errors, hint=hint)

    @classmethod
    def unreadable_version(
        cls, path: str, found: object, supported: frozenset[str]
    ) -> "ContractFormatError":
        msg = f"unknown format version {found!r}; this reader supports {sorted(supported)}"
        return cls(path=path, errors=[("format_version", msg)],
                   hint=_UPGRADE_HINT.format(ver=_reader_version()))

    def _render(self) -> str:
        lines = "\n".join(f"  {loc}: {msg}" for loc, msg in self.errors)
        body = f"{self.path}:\n{lines}"
        if self.hint is not None:
            body += f"\n\n{self.hint}"
        return body
