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


def _load_failure(path: Path) -> list[str] | None:
    """Rendered diagnostic lines for why `path` is not loadable, or None if it loads.

    `Schema.from_yaml` now wraps both the pydantic and the YAML failure into one
    `ContractFormatError` (design §5.1), so lint renders its `.errors` — one line per
    offending key path (§5.2.1) — plus its `.hint` when present. `OSError` still leaks
    from `from_yaml` and is caught here; an unreadable file is not a malformed one.
    """
    try:
        Schema.from_yaml(path)
    except ContractFormatError as exc:
        lines = [f"{loc}: {msg}" for loc, msg in exc.errors]
        if exc.hint:
            lines.append(exc.hint)
        return lines
    except OSError as exc:
        return [f"unreadable — {exc.strerror or exc}"]
    return None


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
        for loc, msg in exc.errors:
            click.echo(f"  - {loc}: {msg}")
        if exc.hint:
            click.echo(f"  {exc.hint}")
        sys.exit(1)
    resolver = Resolver(list(schema_dirs))
    malformed: list[str] = []
    for path in _lintable_schema_files(schema_dirs):
        reasons = _load_failure(path)
        if reasons is not None:
            for reason in reasons:
                malformed.append(f"{path}: {reason}")
    if malformed:
        click.echo("LINT FAILED — malformed schemas:")
        for line in malformed:
            click.echo(f"  - {line}")
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
