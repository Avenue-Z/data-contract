# src/contract_core/cli.py
import sys
from pathlib import Path

import click
from pydantic import ValidationError

from contract_core.compile.odcs import to_odcs, validate_odcs
from contract_core.contract import Contract
from contract_core.resolver import Resolver, SchemaNotFound, _parse_semver
from contract_core.schema import Schema


def _lintable_schema_files(schema_dirs: tuple[str, ...] | list[str]) -> list[Path]:
    """Every schema file the resolver would consider, and no others.

    Scoped to stems `_parse_semver` accepts: that helper returns None rather than raising
    so the major-pin glob skips strays like `latest.yaml` and `_template.yaml`. Linting
    every *.yaml would make a template file a lint error (design §4.1.1).
    """
    files: list[Path] = []
    for d in schema_dirs:
        for p in sorted(Path(d).rglob("*.yaml")):
            if _parse_semver(p.stem) is not None:
                files.append(p)
    return files


@click.group()
def main() -> None:
    """contract — data contract tooling."""


@main.command()
@click.option("--contract", "contract_path", required=True, type=click.Path(exists=True))
@click.option("--schemas", "schema_dirs", multiple=True, required=True,
              type=click.Path(exists=True))
def lint(contract_path: str, schema_dirs: tuple[str, ...]) -> None:
    """Validate a contract: resolve every schema ref and compile to valid ODCS."""
    contract = Contract.from_yaml(contract_path)
    resolver = Resolver(list(schema_dirs))
    malformed: list[str] = []
    for path in _lintable_schema_files(schema_dirs):
        try:
            Schema.from_yaml(path)
        except ValidationError as exc:
            first = exc.errors()[0]["msg"].removeprefix("Value error, ")
            malformed.append(f"{path}: {first}")
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
