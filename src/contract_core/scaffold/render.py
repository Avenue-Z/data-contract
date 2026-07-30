"""Pure template rendering for `contract init` (design 2026-07-30 §2.2, §9).

Substitution is `.replace()`, not `str.format()` — a template's generated content is YAML or
Python and routinely contains literal `{`/`}` (e.g. `source: {kind: api}`), which `.format()`
would misparse. This mirrors tests/conftest.py's existing fixture-string convention.
"""
from __future__ import annotations

from pathlib import Path

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def render(name: str, values: dict[str, str]) -> str:
    path = _TEMPLATES_DIR / name
    text = path.read_text()
    for key, val in values.items():
        text = text.replace("{{" + key + "}}", val)
    return text
