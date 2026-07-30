# src/contract_core/cli.py
import sys
from collections.abc import Sequence
from pathlib import Path

import click

from contract_core.compile.odcs import to_odcs, validate_odcs
from contract_core.contract import Contract
from contract_core.errors import ContractFormatError
from contract_core.resolver import Resolver, SchemaNotFound, parse_semver
from contract_core.schema import Schema


def _lintable_schema_files(schema_dirs: Sequence[str]) -> list[Path]:
    """Every schema file the resolver would consider, and no others.

    Scoped to stems `parse_semver` accepts: that helper returns None rather than raising
    so the major-pin glob skips strays like `latest.yaml` and `_template.yaml`. Linting
    every *.yaml would make a template file a lint error (design §4.1.1).
    """
    files: list[Path] = []
    for d in schema_dirs:
        for p in sorted(Path(d).rglob("*.yaml")):
            if parse_semver(p.stem) is not None:
                files.append(p)
    return files


def _scan_existing_paths(root: Path) -> set[Path]:
    """Every path `contract init` could possibly treat as already-existing, relative to root.

    Narrow by construction (design §2.2): plan() is pure, so this one filesystem walk — over
    exactly the subtrees init could ever write to — is the entire interface it sees.
    """
    paths: set[Path] = set()
    if (root / "contract.yaml").is_file():
        paths.add(Path("contract.yaml"))
    schemas = root / "schemas"
    if schemas.is_dir():
        for p in schemas.rglob("*.yaml"):
            paths.add(p.relative_to(root))
    for pkg_root in (root, root / "src"):
        if pkg_root.is_dir():
            for p in pkg_root.glob("*/boundaries.py"):
                paths.add(p.relative_to(root))
    tests_dir = root / "tests"
    if tests_dir.is_dir():
        for p in tests_dir.glob("test_drift_*.py"):
            paths.add(p.relative_to(root))
    workflow = root / ".github" / "workflows" / "contract.yml"
    if workflow.is_file():
        paths.add(workflow.relative_to(root))
    return paths


def _echo_format_error(exc: ContractFormatError, *, loc_prefix: str = "") -> None:
    """Render a `ContractFormatError` identically wherever it surfaces (design §5.2.1).

    Each per-key error is a bulleted line; `loc_prefix` identifies which file it came from
    when several files are in play (the schema arm). The hint, when present, gets its own
    bare line — no path, no bullet — so it renders as prose, not as another offending key.
    """
    for loc, msg in exc.errors:
        click.echo(f"  - {loc_prefix}{loc}: {msg}")
    if exc.hint:
        click.echo(f"  {exc.hint}")


@click.group()
def main() -> None:
    """contract — data contract tooling."""


@main.command()
@click.option("--contract", "contract_path", required=True, type=click.Path(exists=True))
@click.option("--schemas", "schema_dirs", multiple=True, required=True,
              type=click.Path(exists=True))
def lint(contract_path: str, schema_dirs: tuple[str, ...]) -> None:
    """Validate a contract: resolve every schema ref and compile to valid ODCS."""
    try:
        contract = Contract.from_yaml(contract_path)
    except ContractFormatError as exc:
        click.echo("LINT FAILED — malformed contract:")
        _echo_format_error(exc)
        sys.exit(1)
    resolver = Resolver(list(schema_dirs))
    header_printed = False
    for path in _lintable_schema_files(schema_dirs):
        try:
            Schema.from_yaml(path)
        except ContractFormatError as exc:
            if not header_printed:
                click.echo("LINT FAILED — malformed schemas:")
                header_printed = True
            _echo_format_error(exc, loc_prefix=f"{path}: ")
        except OSError as exc:
            if not header_printed:
                click.echo("LINT FAILED — malformed schemas:")
                header_printed = True
            click.echo(f"  - {path}: unreadable — {exc.strerror or exc}")
    if header_printed:
        sys.exit(1)
    boundaries = [*contract.raw, *contract.inputs, *contract.outputs]
    unresolved = []
    for b in boundaries:
        try:
            resolver.resolve(b.schema_ref)
        except SchemaNotFound as exc:
            # The resolver's message says WHICH of the three ways the ref failed and names
            # the versions that exist. CI reaches lint long before it reaches resolve(), so
            # reprinting the bare ref here strands that diagnosis. `.args[0]` rather than
            # `str(exc)`: SchemaNotFound subclasses KeyError, whose str() is the repr of its
            # argument — quotes and all. Every message already opens with the ref.
            unresolved.append(str(exc.args[0]) if exc.args else b.schema_ref)
    if unresolved:
        click.echo("LINT FAILED — unresolved schema refs:")
        for detail in unresolved:
            click.echo(f"  - {detail}")
        sys.exit(1)
    doc = to_odcs(contract, resolver)
    validate_odcs(doc)
    click.echo(f"OK: {contract.system}@{contract.version} — {len(boundaries)} boundaries resolved")


@main.command()
@click.option("--contract", "contract_path", required=True, type=click.Path(exists=True))
@click.option("--package", "package", required=True)
@click.option("--tests", "test_paths", multiple=True, required=True,
              type=click.Path(exists=True))
def reconcile(contract_path: str, package: str, test_paths: tuple[str, ...]) -> None:
    """Diff declared vs registered boundaries; enforce raw-boundary drift tests (design)."""
    from contract_core.reconcile import reconcile as run
    try:
        result = run(contract_path, package, [Path(p) for p in test_paths])
    except ContractFormatError as exc:
        click.echo("RECONCILE FAILED — malformed contract:")
        _echo_format_error(exc)
        sys.exit(1)
    gating = [f for f in result.findings if f.gating]
    if gating:
        click.echo("RECONCILE FAILED:")
        for f in result.findings:
            click.echo(f"  - {f.message}")
        sys.exit(1)
    for f in result.findings:  # non-gating diagnostics, if any
        click.echo(f"  - {f.message}")
    click.echo(f"OK: {result.system}@{result.version} — "
               f"{result.n_boundaries} boundaries reconciled")


@main.command()
@click.option("--log", "log_path", default=None, type=click.Path())
@click.option("--contract", "contract_path", default=None, type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True)
def events(log_path: str | None, contract_path: str | None, as_json: bool) -> None:
    """Summarize the validation event log: is each boundary safe to promote to `enforce`?"""
    import json as _json

    from contract_core.events import EventLog
    from contract_core.events_report import read_records, render_human, summarize, to_dict

    # Resolve the log path by constructing EventLog, so the $CONTRACT_EVENT_LOG → default fallback
    # is reused by construction rather than reimplemented here (design §2).
    resolved = EventLog(log_path).path
    try:
        records, skipped = read_records(resolved)
    except OSError as exc:
        click.echo(f"EVENTS FAILED — cannot read log {resolved}: {exc.strerror or exc}")
        sys.exit(1)

    contract = None
    if contract_path is not None:
        try:
            contract = Contract.from_yaml(contract_path)
        except ContractFormatError as exc:
            click.echo("EVENTS FAILED — malformed contract:")
            _echo_format_error(exc)
            sys.exit(1)

    report = summarize(records, contract=contract, skipped=skipped)
    if as_json:
        click.echo(_json.dumps(to_dict(report)))
        return
    if not records:
        # The hint fires whether or not --contract was supplied: with a contract and a typo'd --log,
        # every boundary renders [unobserved] and the user gets no signal the path was wrong (§5).
        hint = f"no events recorded at {resolved} — run in observe mode first, or check --log"
        if skipped:
            # Don't launder a corrupt log into "observe never ran": surface the discarded lines,
            # which otherwise only reach --json's summary.skipped and never the human (§ review).
            hint += f" ({skipped} malformed line(s) skipped — the log may be corrupt)"
        click.echo(hint)
        if contract is None:
            return
    click.echo(render_human(report))


@main.command()
@click.option("--system", default=None, help="the contract's system: value")
@click.option("--platform", default=None, help="schema namespace under schemas/<platform>/")
@click.option("--source", "source_kind", default=None,
              type=click.Choice(["api", "mcp", "llm", "file"]),
              help="api/mcp/llm -> mediated; file -> file-ingest")
@click.option("--package", "package_override", default=None,
              help="importable package name; overrides detection")
@click.option("--root", "root_str", default=".", type=click.Path(exists=True, file_okay=False),
              help="target repo root")
@click.option("--dry-run", is_flag=True, help="print the plan report, write nothing")
def init(
    system: str | None, platform: str | None, source_kind: str | None,
    package_override: str | None, root_str: str, dry_run: bool,
) -> None:
    """Scaffold the mechanical steps of adopting a data contract (design 2026-07-30)."""
    from typing import cast

    from contract_core import __version__
    from contract_core.scaffold.apply import apply as run_apply
    from contract_core.scaffold.detect import PackageDetectionError, detect_package
    from contract_core.scaffold.plan import (
        FreshSpec,
        InitSpec,
        PlanError,
        SourceKind,
        render_report,
    )
    from contract_core.scaffold.plan import plan as build_plan

    root = Path(root_str)
    contract_path = root / "contract.yaml"
    given = [f for f, v in (("--system", system), ("--platform", platform),
                             ("--source", source_kind)) if v is not None]

    fresh = None
    existing = None
    if contract_path.is_file():
        if given:
            click.echo(
                f"INIT FAILED — contract.yaml already exists; "
                f"{', '.join(given)} would be ignored, so it is refused instead"
            )
            sys.exit(1)
        try:
            existing = Contract.from_yaml(contract_path)
        except ContractFormatError as exc:
            click.echo("INIT FAILED — malformed contract.yaml:")
            _echo_format_error(exc)
            sys.exit(1)
    else:
        missing = [f for f, v in (("--system", system), ("--platform", platform),
                                   ("--source", source_kind)) if v is None]
        if missing:
            click.echo(f"INIT FAILED — contract.yaml absent; required: {', '.join(missing)}")
            sys.exit(1)
        assert system is not None and platform is not None and source_kind is not None
        fresh = FreshSpec(
            system=system, platform=platform, source_kind=cast(SourceKind, source_kind)
        )

    try:
        detected = detect_package(root, package_override)
    except PackageDetectionError as exc:
        click.echo(f"INIT FAILED — {exc}")
        sys.exit(1)

    spec = InitSpec(
        root=root, package=detected.name, package_dir=detected.package_dir,
        pyproject_text=detected.pyproject_text, contract_core_version=__version__,
        fresh=fresh, existing=existing,
    )
    try:
        result = build_plan(spec, _scan_existing_paths(root))
    except PlanError as exc:
        click.echo(f"INIT FAILED — {exc}")
        sys.exit(1)

    for line in render_report(result):
        click.echo(line)
    for step in result.next_steps:
        click.echo(f"next: {step}")

    if not dry_run:
        run_apply(result, root)
