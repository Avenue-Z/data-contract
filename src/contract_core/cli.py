# src/contract_core/cli.py
import sys
from collections.abc import Sequence
from pathlib import Path

import click
import yaml
from pydantic import ValidationError

from contract_core.compile.odcs import to_odcs, validate_odcs
from contract_core.contract import Contract
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


def _load_failure(path: Path) -> str | None:
    """Why `path` is not a loadable schema, or None if it loads.

    Catches all three ways `Schema.from_yaml` fails, not just the pydantic one. It reads
    the file (OSError) and runs `yaml.safe_load` (YAMLError) BEFORE `model_validate`
    (ValidationError) — and lint now opens files nobody has ever validated, so the first
    two are reachable in a way they were not when lint only parsed referenced schemas.
    An uncaught one exits with a traceback and empty stdout, from the one command whose
    entire job is a readable diagnostic.
    """
    try:
        Schema.from_yaml(path)
    except ValidationError as exc:
        # `msg` is pydantic's documented per-error field; the "Value error, " prefix it
        # wraps a raised ValueError in is presentation, so strip it if present.
        return str(exc.errors()[0]["msg"]).removeprefix("Value error, ")
    except yaml.YAMLError as exc:
        # A syntax error: report the problem line, not the multi-line marked-up dump.
        return f"invalid YAML — {' '.join(str(exc).split())}"
    except OSError as exc:
        return f"unreadable — {exc.strerror or exc}"
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
    contract = Contract.from_yaml(contract_path)
    resolver = Resolver(list(schema_dirs))
    malformed: list[str] = []
    for path in _lintable_schema_files(schema_dirs):
        reason = _load_failure(path)
        if reason is not None:
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
