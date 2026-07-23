# src/contract_core/reconcile.py
"""reconcile — the registration-completeness gate (design 2026-07-23).

Pure functions (diff + AST scans + exception classification) plus a thin impure
orchestrator. Internal module — nothing here is on the public surface (R9).
"""
from dataclasses import dataclass


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
