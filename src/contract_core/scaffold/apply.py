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
    # Compute the pyproject edit BEFORE writing any file. `apply_marker` is the only step that
    # can raise; doing it first keeps the run all-or-nothing (design §2.2) — a failure here
    # leaves the repo untouched instead of half-scaffolded.
    writes_marker = result.marker_action in (MarkerAction.INSERT_KEY, MarkerAction.APPEND_SECTION)
    pyproject_edit: tuple[Path, str] | None = None
    if writes_marker:
        pyproject_path = root / "pyproject.toml"
        edited = apply_marker(pyproject_path.read_text(), result.marker_action)
        pyproject_edit = (pyproject_path, edited)

    for t in targets:
        _write_target(root, t)
    if pyproject_edit is not None:
        pyproject_edit[0].write_text(pyproject_edit[1])


def _write_target(root: Path, target: Target) -> None:
    if target.status != "created":
        return
    path = root / target.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(target.content)
