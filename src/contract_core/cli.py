# src/contract_core/cli.py
import sys

import click

from contract_core.compile.odcs import to_odcs, validate_odcs
from contract_core.contract import Contract
from contract_core.resolver import Resolver, SchemaNotFound


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
