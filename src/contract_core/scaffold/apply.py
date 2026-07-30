"""Execute a Plan (design 2026-07-30 §2.2) — the only writer in the scaffold package.

Every create/skip decision was already made, purely, by plan.py — this module's only job is I/O:
write what `plan()` said to create, and never touch what it said already exists.
"""
from __future__ import annotations

from pathlib import Path

from contract_core.scaffold.plan import Plan, Target
from contract_core.scaffold.pyproject import MarkerAction, apply_marker


def apply(result: Plan, root: Path) -> None:
    targets = (
        [*result.other_targets] if result.is_rerun
        else [result.contract_target, *result.other_targets]
    )
    for t in targets:
        _write_target(root, t)
    if result.marker_action in (MarkerAction.INSERT_KEY, MarkerAction.APPEND_SECTION):
        pyproject_path = root / "pyproject.toml"
        text = pyproject_path.read_text()
        pyproject_path.write_text(apply_marker(text, result.marker_action))


def _write_target(root: Path, target: Target) -> None:
    if target.status != "created":
        return
    path = root / target.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(target.content)
