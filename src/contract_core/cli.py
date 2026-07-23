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
            resolver.resolve(b.schema)
        except SchemaNotFound:
            unresolved.append(b.schema)
    if unresolved:
        click.echo("LINT FAILED — unresolved schema refs:")
        for ref in unresolved:
            click.echo(f"  - {ref}")
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
