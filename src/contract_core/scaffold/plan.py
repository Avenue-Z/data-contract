"""Pure planning for `contract init` (design 2026-07-30 §2.2, §3, §4, §5).

No writes. `plan()` reads only the packaged `.tmpl` files (via `render()`); it never touches the
target repo. Every validation failure (bad --system/--platform, flags-with-existing-contract) and
every created/skipped decision is decided here, purely from `existing_paths`, before apply.py writes
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
    pyproject_text: str             # the snapshot guard_marker classified; apply transforms THIS
    dependency_line: str
    next_steps: list[str]


def _validate_identifier(flag: str, value: str) -> None:
    """Both `--system` and `--platform` are interpolated unquoted into contract.yaml via naive
    `.replace()`; an unvalidated value (e.g. `a: b`) yields a tree that lints as malformed YAML,
    breaking the correct-by-construction guarantee. Restrict to the same charset (design §7)."""
    if not value:
        raise PlanError(f"{flag} must be a non-empty string of letters, digits, '_' and '-'")
    for ch in value:
        if not _PLATFORM_RE.fullmatch(ch):
            raise PlanError(
                f"{flag} {value!r} contains {ch!r}; only letters, digits, "
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


def _major_already_present(schema_dir: Path, version: str, existing_paths: set[Path]) -> bool:
    """design §5.1: gap-fill declines writing a schema file only when the ref is ALREADY
    satisfied — which for a `@MAJOR` pin means a file with that same major exists (resolver
    resolves `@1` against any `1.x.x`, `v[0]==major`). A stray file of a *different* major
    (`2.0.0.yaml` under an `@1` ref) leaves the ref dangling, so it must NOT suppress the write.
    Exact `@MAJOR.MINOR.PATCH` refs are satisfied only by their own file — handled by the
    `path in existing_paths` check in `_plan_schemas`, so this returns False for them. A
    non-semver stray (`_template.yaml`) never counts (mirrors `parse_semver`'s skip-strays)."""
    if not version.isdigit():
        return False
    major = int(version)
    return any(
        p.parent == schema_dir
        and (parsed := parse_semver(p.stem)) is not None
        and parsed[0] == major
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
        if (path not in existing_paths
                and _major_already_present(schema_dir, version, existing_paths)):
            targets.append(Target(
                path, content="", exists=True, skip_reason="schema major already present"
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


# Each archetype's boundaries.py template carries exactly one stanza per direction listed here.
# A faithful render therefore needs exactly one boundary in each — see `_require_scaffoldable`.
_TEMPLATE_DIRECTIONS: dict[Archetype, tuple[str, ...]] = {
    "mediated": ("raw", "input", "output"),
    "file-ingest": ("input", "output"),
}


def _require_scaffoldable(archetype: Archetype, boundaries: list[ResolvedBoundary]) -> None:
    """The boundaries.py templates render one stanza per direction via `.replace()`; they cannot
    loop. A contract with 2+ (or 0) boundaries in a template direction can't be faithfully
    regenerated — a dict keyed by direction would drop all but the last, and an absent direction
    would leave `{{DIR_NAME}}` unsubstituted. Rather than emit a boundaries.py that fails its own
    reconcile, refuse (design §5: nothing partial is written; the author wires it by hand)."""
    counts = {d: sum(1 for b in boundaries if b.direction == d) for d in ("raw", "input", "output")}
    offenders = [
        f"{counts[d]} {d} boundaries" for d in _TEMPLATE_DIRECTIONS[archetype] if counts[d] != 1
    ]
    if offenders:
        raise PlanError(
            f"contract.yaml declares {', '.join(offenders)}; `contract init` scaffolds "
            f"boundaries.py with exactly one stanza per direction. Author boundaries.py by hand "
            f"(one @runtime.<direction>(...) per boundary), then re-run to gap-fill the rest."
        )


def _plan_boundaries_py(
    spec: InitSpec, archetype: Archetype, boundaries: list[ResolvedBoundary],
    existing_paths: set[Path],
) -> Target:
    template = (
        "boundaries.mediated.py.tmpl" if archetype == "mediated"
        else "boundaries.file-ingest.py.tmpl"
    )
    rel_dir = spec.package_dir.relative_to(spec.root)
    path = rel_dir / "boundaries.py"
    exists = path in existing_paths
    if not exists:
        # Only guard the write path: an already-wired boundaries.py is skipped, so a multi-boundary
        # contract the author has themselves wired stays a valid fixed point.
        _require_scaffoldable(archetype, boundaries)
    values = {f"{b.direction.upper()}_NAME": b.name for b in boundaries}
    content = render(template, values)
    return Target(path, content, exists=exists)


def _plan_drift_test(spec: InitSpec, raw: ResolvedBoundary, existing_paths: set[Path]) -> Target:
    content = render("drift_test.py.tmpl", {"PACKAGE": spec.package, "RAW_NAME": raw.name})
    path = Path("tests") / f"test_drift_{raw.name}.py"
    return Target(path, content, exists=path in existing_paths)


def _plan_tests_placeholder(existing_paths: set[Path]) -> Target:
    """File-ingest has no drift test, so nothing else creates tests/. The generated gate runs
    `contract reconcile --tests tests` (required, must exist), so without this a scaffolded
    file-ingest repo would fail its own gate. A tracked placeholder keeps the dir present;
    reconcile finds no raw-drift test required (no raw boundary) and exits 0."""
    path = Path("tests") / ".gitkeep"
    return Target(path, content="", exists=path in existing_paths)


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
        # One drift test per raw boundary — `reconcile` emits a gating `D` finding for EVERY
        # uncovered raw (reconcile.py), so covering only the first would fail its own reconcile
        # on the multi-raw re-run path (a fresh run only ever has one raw).
        for raw in (b for b in boundaries if b.direction == "raw"):
            targets.append(_plan_drift_test(spec, raw, existing_paths))
    else:
        targets.append(_plan_tests_placeholder(existing_paths))
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
        _validate_identifier("--system", spec.fresh.system)
        _validate_identifier("--platform", spec.fresh.platform)
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
        marker_action=marker_action, pyproject_text=spec.pyproject_text,
        dependency_line=dependency_line, next_steps=next_steps,
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
