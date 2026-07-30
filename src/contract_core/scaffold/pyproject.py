"""The pyproject.toml marker guard ladder (design 2026-07-30 §8).

Never round-trips TOML: `guard_marker` only ever READS (via `tomllib`, stdlib, read-only) to
classify which rung applies; `apply_marker` only ever APPENDS or INSERTS text. There is no
general-purpose TOML writer here on purpose — this repo has none, and mangling a working
pytest config would be worse than the step this module automates (design §8).
"""
from __future__ import annotations

import tomllib
from enum import Enum

_MARKER_NAME = "raw_drift"
_MARKER_LINE = '"raw_drift: a drift test guarding a raw boundary (read by `contract reconcile`)"'
_SECTION_HEADER = "[tool.pytest.ini_options]"

MANUAL_SNIPPET = (
    "pyproject.toml already declares [tool.pytest.ini_options].markers without `raw_drift`.\n"
    "`init` will not edit an existing array — its formatting (inline/multiline, trailing\n"
    "commas, comments) is not append-safe to guess at. Add this element yourself:\n\n"
    f"  {_MARKER_LINE}\n"
)


class MarkerAction(Enum):
    SATISFIED = "satisfied"            # rung 1 — nothing to do
    MANUAL = "manual"                  # rung 2 — refuse; print MANUAL_SNIPPET
    INSERT_KEY = "insert_key"          # rung 3 — section exists, no markers key
    APPEND_SECTION = "append_section"  # rung 4 — section absent entirely


def guard_marker(pyproject_text: str) -> MarkerAction:
    """Classify which rung of the guard ladder `pyproject_text` falls on (design §8 table).

    Read-only: parses with `tomllib` to find the `markers` array, if any, and never writes.
    Callers only ever pass text this process has already read+parsed successfully (design §7
    step 1 always runs first), so an absent/unparseable file is not a case this function handles.
    """
    data = tomllib.loads(pyproject_text)
    pytest_opts = data.get("tool", {}).get("pytest", {}).get("ini_options")
    if pytest_opts is None:
        return MarkerAction.APPEND_SECTION
    markers = pytest_opts.get("markers")
    if markers is None:
        return MarkerAction.INSERT_KEY
    for m in markers:
        if str(m).split(":", 1)[0].strip() == _MARKER_NAME:
            return MarkerAction.SATISFIED
    return MarkerAction.MANUAL


def apply_marker(pyproject_text: str, action: MarkerAction) -> str:
    """Text-append the marker per `action` (design §8). Pure string manipulation, no TOML writer.

    Never called for SATISFIED (nothing to do) or MANUAL (refused — see MANUAL_SNIPPET).
    """
    if action is MarkerAction.APPEND_SECTION:
        return pyproject_text.rstrip("\n") + f"\n\n{_SECTION_HEADER}\nmarkers = [{_MARKER_LINE}]\n"
    if action is MarkerAction.INSERT_KEY:
        return _insert_markers_key(pyproject_text)
    raise ValueError(f"apply_marker called with a non-writing action: {action!r}")


def _insert_markers_key(text: str) -> str:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line.strip() == _SECTION_HEADER:
            out.append(f"markers = [{_MARKER_LINE}]\n")
            inserted = True
    if not inserted:
        raise ValueError(f"insert_key called but {_SECTION_HEADER!r} was not found")
    return "".join(out)
