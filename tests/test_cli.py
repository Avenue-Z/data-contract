# tests/test_cli.py
from pathlib import Path

from click.testing import CliRunner

from contract_core.cli import _lintable_schema_files, main

FIX = Path(__file__).parent / "fixtures"


def test_lint_ok():
    runner = CliRunner()
    res = runner.invoke(main, ["lint", "--contract", str(FIX / "contract_lintable.yaml"),
                               "--schemas", str(FIX / "schemas")])
    assert res.exit_code == 0, res.output
    assert "OK" in res.output


def test_lint_unresolved_ref_fails():
    runner = CliRunner()
    res = runner.invoke(main, ["lint", "--contract", str(FIX / "contract_broken.yaml"),
                               "--schemas", str(FIX / "schemas")])
    assert res.exit_code == 1
    assert "peec.nonexistent@1" in res.output


# ---- lint validates every resolver-visible schema (design §4.1.1) ----

def _lint_with_malformed():
    """Lint a valid contract against BOTH schema roots, one of which holds a bad schema.

    The malformed fixture is kept in its own root so `test_lint_ok` — which lints only
    tests/fixtures/schemas and expects exit 0 — keeps meaning what it says.
    """
    return CliRunner().invoke(main, [
        "lint",
        "--contract", str(FIX / "contract_lintable.yaml"),
        "--schemas", str(FIX / "schemas"),
        "--schemas", str(FIX / "schemas_malformed"),
    ])


def test_lint_reports_a_malformed_constraint_in_an_unreferenced_schema():
    # 3.0.0 is referenced by no fixture contract. Design §4.1.1: lint must still see it,
    # or the authoring error surfaces at import time in production instead.
    result = _lint_with_malformed()
    assert result.exit_code == 1
    assert "LINT FAILED" in result.output
    assert "3.0.0" in result.output
    assert "min_length applies to string" in result.output


def test_lint_does_not_raise_a_traceback_on_a_malformed_schema():
    result = _lint_with_malformed()
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_lint_ignores_non_semver_files_like_latest_yaml():
    # `_parse_semver` returns None rather than raising SPECIFICALLY so the major-pin glob
    # skips latest.yaml and _template.yaml. Linting every *.yaml would turn a deliberate
    # accommodation into a failure (design §4.1.1).
    names = {p.name for p in _lintable_schema_files([str(FIX / "schemas")])}
    assert "latest.yaml" not in names
    assert "1.0.0.yaml" in names


def test_lint_reports_unparseable_yaml_instead_of_crashing():
    # Task 8 widened lint from "schemas the contract references" to "every schema file
    # under every --schemas root", so it now opens files nobody has ever validated.
    # `Schema.from_yaml` runs yaml.safe_load before model_validate: a syntax error raises
    # yaml.YAMLError, never ValidationError. Catching only the latter produced exit 1 with
    # EMPTY stdout and a ParserError traceback.
    result = _lint_with_malformed()
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "4.0.0" in result.output
    assert "LINT FAILED" in result.output
