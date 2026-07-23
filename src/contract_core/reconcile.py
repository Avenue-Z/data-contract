# src/contract_core/reconcile.py
"""reconcile — the registration-completeness gate (design 2026-07-23).

Pure functions (diff + AST scans + exception classification) plus a thin impure
orchestrator. Internal module — nothing here is on the public surface (R9).
"""
import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from contract_core.errors import UndeclaredBoundary


@dataclass(frozen=True)
class Finding:
    category: str      # "P" | "A" | "B" | "C" | "D" | "diagnostic"
    identifier: str    # portable id: "direction:name", boundary name, module, or "file:line"
    message: str       # human-readable line for the CLI

    @property
    def gating(self) -> bool:
        return self.category != "diagnostic"


# Fixed render/sort order so golden CLI tests and CI diffs are stable (design §5.2).
_CATEGORY_RANK = {"P": 0, "A": 1, "B": 2, "C": 3, "D": 4, "diagnostic": 5}


def _sort_key(f: Finding) -> tuple[int, str]:
    return (_CATEGORY_RANK[f.category], f.identifier)


def diff_boundaries(
    declared: set[tuple[str, str]], registered: set[tuple[str, str]]
) -> list[Finding]:
    """Category A for every declared boundary no decorator registered (design §5, §2).

    The reverse (registered − declared) is structurally empty — an undeclared name raises
    `UndeclaredBoundary` before the append — so it is reported only as a non-gating
    diagnostic if it ever somehow occurs.
    """
    findings: list[Finding] = []
    for direction, name in declared - registered:
        findings.append(Finding(
            "A", f"{direction}:{name}",
            f"declared but no decorator registered it: {direction} '{name}'"))
    for direction, name in registered - declared:
        findings.append(Finding(
            "diagnostic", f"{direction}:{name}",
            f"registered but not declared: {direction} '{name}'"))
    return sorted(findings, key=_sort_key)


_BOUNDARY_ATTRS = {"raw", "input", "output"}


def _is_boundary_decorator(dec: ast.expr) -> bool:
    """`@<x>.raw|input|output("literal")` — decorator position, attribute form, one string
    literal arg (design §6.3). The narrowings keep the over-match small and measured."""
    return (
        isinstance(dec, ast.Call)
        and isinstance(dec.func, ast.Attribute)
        and dec.func.attr in _BOUNDARY_ATTRS
        and len(dec.args) == 1
        and isinstance(dec.args[0], ast.Constant)
        and isinstance(dec.args[0].value, str)
    )


def scan_decorator_placement(files: Iterable[Path]) -> list[Finding]:
    """Category C: a boundary decorator not at module top level would not run at import,
    so force-import never registers it — a silent false pass (design §6.3, R3)."""
    findings: list[Finding] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue  # unparseable file surfaces as an import diagnostic, not here
        top_level = {
            id(n) for n in ast.iter_child_nodes(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if id(node) in top_level:
                continue
            for dec in node.decorator_list:
                if _is_boundary_decorator(dec):
                    assert (
                        isinstance(dec, ast.Call)
                        and isinstance(dec.func, ast.Attribute)
                        and isinstance(dec.args[0], ast.Constant)
                        and isinstance(dec.args[0].value, str)
                    )
                    name = dec.args[0].value
                    findings.append(Finding(
                        "C", f"{path}:{node.lineno}",
                        f"boundary decorator @…{dec.func.attr}('{name}') not at module "
                        f"top level ({path}:{node.lineno})"))
    return sorted(findings, key=_sort_key)


def scan_drift_markers(files: Iterable[Path]) -> set[str]:
    """The set of raw-boundary names covered by an `@…raw_drift("name")` decorator (§7.1).

    Decorator position only, attribute form (`.attr == "raw_drift"`), string-literal args
    only — every residual fails toward firing category D (over-strict, never a false pass)."""
    covered: set[str] = set()
    for path in files:
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and dec.func.attr == "raw_drift"):
                    for arg in dec.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            covered.add(arg.value)
    return covered


def _find_undeclared(exc: BaseException) -> UndeclaredBoundary | None:
    """Walk the exception chain — a module may catch and re-raise `from` an
    UndeclaredBoundary; missing it would silently drop an undeclared boundary (design §6.2)."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, UndeclaredBoundary):
            return cur
        cur = cur.__cause__ or cur.__context__
    return None


def classify_import_error(
    module: str, exc: BaseException, *, fatal: bool = False
) -> Finding:
    """Turn an import-time exception into a finding (design §6.2).

    `UndeclaredBoundary` anywhere in the chain gates as B (by type, never message-parsing).
    Otherwise: P when fatal (top-level import — no category-A backstop below it), else a
    non-gating diagnostic. Message carries only the exception type, never env-specific
    text (§5.2)."""
    ub = _find_undeclared(exc)
    if ub is not None:
        return Finding("B", ub.name,
                       f"decorator names an undeclared boundary '{ub.name}' (in {module})")
    if fatal:
        return Finding("P", module,
                       f"package '{module}' could not be imported: {type(exc).__name__}")
    return Finding("diagnostic", module,
                   f"module '{module}' failed to import: {type(exc).__name__}")
