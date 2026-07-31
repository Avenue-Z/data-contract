"""Package detection for `contract init` (design 2026-07-30 §7) — read-only I/O.

Step 1 (reading pyproject.toml) always runs, even when `--package` is given: its existence and
parseability are part of the §1.1 entry state, and the marker guard ladder (pyproject.py) needs
its text regardless. `--package` only overrides the NAME derived in step 2, never this read.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


class PackageDetectionError(Exception):
    """A fatal §7 detection failure. There is no degraded mode (design §7)."""


@dataclass(frozen=True)
class DetectedPackage:
    name: str
    package_dir: Path       # absolute; the dir holding __init__.py
    pyproject_text: str     # already-read text, reused by plan()'s marker guard (design §8)


def detect_package(root: Path, package_override: str | None) -> DetectedPackage:
    pyproject_path = root / "pyproject.toml"
    try:
        text = pyproject_path.read_text()
    except OSError as exc:
        raise PackageDetectionError(
            f"cannot read {pyproject_path}: {exc.strerror or exc}; pass --package"
        ) from exc
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PackageDetectionError(
            f"{pyproject_path} is not valid TOML: {exc}; pass --package"
        ) from exc

    if package_override is not None:
        name = package_override
    else:
        project_name = data.get("project", {}).get("name")
        if not project_name:
            raise PackageDetectionError(
                f"{pyproject_path} has no [project].name; pass --package"
            )
        name = project_name.replace("-", "_")

    flat = root / name / "__init__.py"
    src = root / "src" / name / "__init__.py"
    flat_exists, src_exists = flat.is_file(), src.is_file()

    if flat_exists and src_exists:
        raise PackageDetectionError(
            f"both {flat} and {src} exist for package {name!r} — cannot tell which layout is "
            f"importable; remove the stale one, or pass --package"
        )
    if flat_exists:
        return DetectedPackage(name, flat.parent, text)
    if src_exists:
        return DetectedPackage(name, src.parent, text)
    raise PackageDetectionError(
        f"neither {flat} nor {src} exists — {name!r} is not on disk as an installable "
        f"package; pass --package"
    )
