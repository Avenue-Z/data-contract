# tests/test_cli.py
from pathlib import Path

from click.testing import CliRunner

from contract_core.cli import main

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
