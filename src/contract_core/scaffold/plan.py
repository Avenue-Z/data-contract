"""Pure planning for `contract init` (design 2026-07-30 §2.2, §3, §4, §5).

No I/O. Every validation failure (bad --platform, flags-with-existing-contract) and every
created/skipped decision is decided here, purely from `existing_paths`, before apply.py writes
anything — this is what lets --dry-run and a real run share one code path (design §2.2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from contract_core.contract import Contract
from contract_core.resolver import parse_semver
from contract_core.scaffold.pyproject import MANUAL_SNIPPET, MarkerAction, guard_marker
from contract_core.scaffold.render import render

SourceKind = Literal["api", "mcp", "llm", "file"]
Archetype = Literal["mediated", "file-ingest"]
_MEDIATED_KINDS: frozenset[str] = frozenset({"api", "mcp", "llm"})
_PLATFORM_RE = re.compile(r"[A-Za-z0-9_-]")


class PlanError(Exception):
    """A validation failure found during planning (design §2.2) — nothing has been written."""


@dataclass(frozen=True)
class FreshSpec:
    system: str
    platform: str
    source_kind: SourceKind


@dataclass(frozen=True)
class InitSpec:
    root: Path
    package: str
    package_dir: Path          # absolute
    pyproject_text: str
    contract_core_version: str
    fresh: FreshSpec | None    # set exactly when contract.yaml is absent
    existing: Contract | None  # set exactly when contract.yaml is present


@dataclass(frozen=True)
class ResolvedBoundary:
    direction: Literal["raw", "input", "output"]
    name: str
    schema_ref: str


@dataclass(frozen=True)
class Target:
    path: Path                  # relative to root
    content: str
    exists: bool
    skip_reason: str = "exists"

    @property
    def status(self) -> Literal["created", "skipped"]:
        return "skipped" if self.exists else "created"


@dataclass(frozen=True)
class Plan:
    is_rerun: bool
    system: str
    archetype: Archetype
    contract_target: Target
    other_targets: list[Target]     # everything except contract.yaml, in write order
    marker_action: MarkerAction
    dependency_line: str
    next_steps: list[str]


def _validate_platform(platform: str) -> None:
    for ch in platform:
        if not _PLATFORM_RE.fullmatch(ch):
            raise PlanError(
                f"--platform {platform!r} contains {ch!r}; only letters, digits, "
                f"'_' and '-' are allowed"
            )


def _archetype_of(source_kind: str) -> Archetype:
    return "mediated" if source_kind in _MEDIATED_KINDS else "file-ingest"


def _boundaries_for_fresh(fresh: FreshSpec) -> list[ResolvedBoundary]:
    p = fresh.platform
    archetype = _archetype_of(fresh.source_kind)
    boundaries = []
    if archetype == "mediated":
        boundaries.append(ResolvedBoundary("raw", f"{p}_raw", f"{p}.raw_report@1"))
    boundaries.append(ResolvedBoundary("input", "records", f"{p}.records@1"))
    boundaries.append(ResolvedBoundary("output", "report", f"{p}.report@1"))
    return boundaries


def _split_ref(ref: str) -> tuple[str, str]:
    name, _, version = ref.partition("@")
    return name, version


def _schema_version_body(version: str) -> str:
    """The schema body's own `version:` value — a full semver even for an @MAJOR ref."""
    return version if "." in version else f"{version}.0.0"


_KIND_TEMPLATE = {
    "raw": ("schema.payload.yaml.tmpl", "the vendor's raw payload"),
    "input": ("schema.tabular.yaml.tmpl", "the normalized rows"),
    "output": ("schema.payload.yaml.tmpl", "your deliverable"),
}


def _plan_contract_yaml(
    spec: InitSpec, system: str, boundaries: list[ResolvedBoundary],
    source_kind: str, source_format: str, existing_paths: set[Path],
) -> Target:
    template = (
        "contract.mediated.yaml.tmpl" if source_kind in _MEDIATED_KINDS
        else "contract.file-ingest.yaml.tmpl"
    )
    values = {"SYSTEM": system, "SOURCE_KIND": source_kind, "SOURCE_FORMAT": source_format}
    for b in boundaries:
        key = b.direction.upper()
        values[f"{key}_NAME"] = b.name
        values[f"{key}_REF"] = b.schema_ref
    content = render(template, values)
    path = Path("contract.yaml")
    return Target(path, content, exists=path in existing_paths)


def _boundaries_for_existing(contract: Contract) -> list[ResolvedBoundary]:
    boundaries = [ResolvedBoundary("raw", b.name, b.schema_ref) for b in contract.raw]
    boundaries += [ResolvedBoundary("input", b.name, b.schema_ref) for b in contract.inputs]
    boundaries += [ResolvedBoundary("output", b.name, b.schema_ref) for b in contract.outputs]
    return boundaries


def _schema_dir_occupied(schema_dir: Path, existing_paths: set[Path]) -> bool:
    """design §5.1: gap-fill declines whenever the directory already holds ANY semver-named
    file — not just the one this ref would write. A non-semver stray (`_template.yaml`) does
    not count, mirroring `parse_semver`'s own "skip strays" contract (resolver.py)."""
    return any(
        p.parent == schema_dir and parse_semver(p.stem) is not None
        for p in existing_paths
    )


def _plan_schemas(boundaries: list[ResolvedBoundary], existing_paths: set[Path]) -> list[Target]:
    schemas_root = Path("schemas")
    targets = []
    for b in boundaries:
        name, version = _split_ref(b.schema_ref)
        schema_dir = schemas_root.joinpath(*name.split("."))
        filename = f"{version}.yaml" if "." in version else f"{version}.0.0.yaml"
        path = schema_dir / filename
        if path not in existing_paths and _schema_dir_occupied(schema_dir, existing_paths):
            targets.append(Target(
                path, content="", exists=True, skip_reason="schema directory not empty"
            ))
            continue
        template, description = _KIND_TEMPLATE[b.direction]
        content = render(template, {
            "SCHEMA_NAME": name,
            "VERSION": _schema_version_body(version),
            "DESCRIPTION": description,
        })
        targets.append(Target(path, content, exists=path in existing_paths))
    return targets


def _plan_boundaries_py(
    spec: InitSpec, archetype: Archetype, boundaries: list[ResolvedBoundary],
    existing_paths: set[Path],
) -> Target:
    template = (
        "boundaries.mediated.py.tmpl" if archetype == "mediated"
        else "boundaries.file-ingest.py.tmpl"
    )
    values = {f"{b.direction.upper()}_NAME": b.name for b in boundaries}
    content = render(template, values)
    rel_dir = spec.package_dir.relative_to(spec.root)
    path = rel_dir / "boundaries.py"
    return Target(path, content, exists=path in existing_paths)


def _plan_drift_test(spec: InitSpec, raw: ResolvedBoundary, existing_paths: set[Path]) -> Target:
    content = render("drift_test.py.tmpl", {"PACKAGE": spec.package, "RAW_NAME": raw.name})
    path = Path("tests") / f"test_drift_{raw.name}.py"
    return Target(path, content, exists=path in existing_paths)


def _plan_ci_workflow(
    spec: InitSpec, archetype: Archetype, existing_paths: set[Path],
) -> Target:
    template = (
        "ci-workflow.mediated.yml.tmpl" if archetype == "mediated"
        else "ci-workflow.file-ingest.yml.tmpl"
    )
    content = render(template, {"TAG": spec.contract_core_version, "PACKAGE": spec.package})
    path = Path(".github/workflows/contract.yml")
    return Target(path, content, exists=path in existing_paths)


def _common_targets(
    spec: InitSpec, archetype: Archetype, boundaries: list[ResolvedBoundary],
    existing_paths: set[Path],
) -> list[Target]:
    targets = _plan_schemas(boundaries, existing_paths)
    targets.append(_plan_boundaries_py(spec, archetype, boundaries, existing_paths))
    if archetype == "mediated":
        raw = next(b for b in boundaries if b.direction == "raw")
        targets.append(_plan_drift_test(spec, raw, existing_paths))
    targets.append(_plan_ci_workflow(spec, archetype, existing_paths))
    return targets


def _next_steps(
    spec: InitSpec, archetype: Archetype, marker_action: MarkerAction, dependency_line: str,
) -> list[str]:
    steps = [
        "pin the dependency — add this line to pyproject.toml's [project].dependencies:\n"
        f"    {dependency_line!r}"
    ]
    if archetype == "mediated":
        steps.append(
            "the generated drift test fails on purpose (GENERATED PLACEHOLDER) — the `drift` "
            "job in .github/workflows/contract.yml makes that red visible; write the real "
            "assertion in the drift test to clear it"
        )
    if marker_action is MarkerAction.MANUAL:
        steps.append(f"register the raw_drift marker by hand:\n{MANUAL_SNIPPET}")
    return steps


def plan(spec: InitSpec, existing_paths: set[Path]) -> Plan:
    if (spec.fresh is None) == (spec.existing is None):
        raise PlanError("internal: exactly one of InitSpec.fresh/.existing must be set")

    if spec.fresh is not None:
        _validate_platform(spec.fresh.platform)
        system = spec.fresh.system
        archetype = _archetype_of(spec.fresh.source_kind)
        boundaries = _boundaries_for_fresh(spec.fresh)
        source_format = "json" if archetype == "mediated" else "csv"
        contract_target = _plan_contract_yaml(
            spec, system, boundaries, spec.fresh.source_kind, source_format, existing_paths
        )
        is_rerun = False
    else:
        contract = spec.existing
        assert contract is not None
        system = contract.system
        archetype = "mediated" if contract.raw else "file-ingest"
        boundaries = _boundaries_for_existing(contract)
        contract_target = Target(Path("contract.yaml"), content="", exists=True)
        is_rerun = True

    other_targets = _common_targets(spec, archetype, boundaries, existing_paths)
    marker_action = guard_marker(spec.pyproject_text)
    dependency_line = (
        f"contract-core @ git+https://github.com/Avenue-Z/data-contract.git"
        f"@v{spec.contract_core_version}"
    )
    next_steps = _next_steps(spec, archetype, marker_action, dependency_line)

    return Plan(
        is_rerun=is_rerun, system=system, archetype=archetype,
        contract_target=contract_target, other_targets=other_targets,
        marker_action=marker_action, dependency_line=dependency_line, next_steps=next_steps,
    )


_MARKER_REPORT_LINE = {
    MarkerAction.SATISFIED: "satisfied pyproject.toml (raw_drift marker already registered)",
    MarkerAction.MANUAL: "manual   pyproject.toml (raw_drift marker — see printed snippet)",
    MarkerAction.INSERT_KEY: "edited   pyproject.toml (raw_drift marker)",
    MarkerAction.APPEND_SECTION: "edited   pyproject.toml (raw_drift marker)",
}


def render_report(p: Plan) -> list[str]:
    """Design §5: one line per target in plan order, consecutive skips collapsed to a count.

    Pure — a function of `Plan` alone, which is what lets --dry-run print this before any write.
    """
    lines: list[str] = []
    if p.is_rerun:
        lines.append(f"read      contract.yaml ({p.system}, {p.archetype})")
        rest = p.other_targets
    else:
        rest = [p.contract_target, *p.other_targets]

    i = 0
    while i < len(rest):
        t = rest[i]
        if t.status == "created":
            lines.append(f"created  {t.path}")
            i += 1
            continue
        reason = t.skip_reason
        j = i
        while j < len(rest) and rest[j].status == "skipped" and rest[j].skip_reason == reason:
            j += 1
        count = j - i
        if count == 1:
            lines.append(f"skipped  {t.path} ({reason})")
        else:
            lines.append(f"skipped  {count} files ({reason})")
        i = j

    lines.append(_MARKER_REPORT_LINE[p.marker_action])
    return lines
