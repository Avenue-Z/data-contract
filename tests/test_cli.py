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
    # `parse_semver` returns None rather than raising SPECIFICALLY so the major-pin glob
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


def test_lint_reports_a_malformed_contract_without_a_traceback():
    runner = CliRunner()
    res = runner.invoke(main, ["lint", "--contract", str(FIX / "contract_malformed.yaml"),
                               "--schemas", str(FIX / "schemas")])
    assert res.exit_code == 1
    assert res.exception is None or isinstance(res.exception, SystemExit)
    assert "LINT FAILED" in res.output
    assert "systemm" in res.output  # names the offending key path


def test_lint_names_every_unknown_key_and_prints_the_hint():
    # Criterion 14: the operator's STDOUT, not the exception. Two unknown keys -> two lines,
    # plus the upgrade hint, from a schema authored for a newer format.
    import tempfile
    import textwrap
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "peec" / "prompts_export"
        root.mkdir(parents=True)
        (root / "9.0.0.yaml").write_text(textwrap.dedent("""\
            schema: peec.prompts_export
            version: 9.0.0
            kind: tabular
            fields:
              - name: prompt
                type: string
                pattern: "^x$"
                max_length: 5
        """))
        res = CliRunner().invoke(main, [
            "lint", "--contract", str(FIX / "contract_lintable.yaml"),
            "--schemas", str(FIX / "schemas"), "--schemas", d])
    assert res.exit_code == 1
    assert "pattern" in res.output
    assert "max_length" in res.output
    assert "Upgrade the pin" in res.output


def test_lint_schema_hint_is_not_glued_to_the_path():
    # Regression: the schema arm used to prefix EVERY rendered line — including the hint —
    # with "{path}: ", so the hint read as "path/to/9.0.0.yaml: The file was likely
    # authored against a newer contract-core... Upgrade the pin ...". The contract arm
    # already rendered the hint on its own bare line; the two arms must match.
    import tempfile
    import textwrap
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "peec" / "prompts_export"
        root.mkdir(parents=True)
        (root / "9.0.0.yaml").write_text(textwrap.dedent("""\
            schema: peec.prompts_export
            version: 9.0.0
            kind: tabular
            fields:
              - name: prompt
                type: string
                pattern: "^x$"
                max_length: 5
        """))
        res = CliRunner().invoke(main, [
            "lint", "--contract", str(FIX / "contract_lintable.yaml"),
            "--schemas", str(FIX / "schemas"), "--schemas", d])
    assert res.exit_code == 1
    lines = res.output.splitlines()
    hint_lines = [line for line in lines if "Upgrade the pin" in line]
    assert hint_lines, res.output
    assert all(":" not in line.split("Upgrade the pin")[0] for line in hint_lines), res.output


def test_lint_malformed_contract_names_every_key_and_prints_the_hint():
    # Drives the contract arm directly (not the schema-malformed path above): a contract
    # with TWO unknown top-level keys, against a valid --schemas root so schema resolution
    # is never reached. Asserts the `if exc.hint:` branch at cli.py actually fires.
    import tempfile
    import textwrap
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "contract_two_unknown_keys.yaml"
        p.write_text(textwrap.dedent("""\
            system: aivx-reports
            version: 1.0.0
            systemm: typo-of-system
            verzion: typo-of-version
        """))
        res = CliRunner().invoke(main, [
            "lint", "--contract", str(p), "--schemas", str(FIX / "schemas")])
    assert res.exit_code == 1
    assert res.exception is None or isinstance(res.exception, SystemExit)
    assert "LINT FAILED — malformed contract:" in res.output
    assert "systemm" in res.output
    assert "verzion" in res.output
    assert "Upgrade the pin" in res.output


def _drift_dir(tmp_path):
    d = tmp_path / "drifts"
    d.mkdir()
    (d / "drift_prompts_raw.py").write_text(
        "import pytest\n@pytest.mark.raw_drift('prompts_raw')\ndef test_x():\n    pass\n")
    return d


def test_reconcile_clean_exits_zero(make_reconcile_pkg, reconcile_sources, tmp_path):
    pkg = make_reconcile_pkg({"boundaries.py": reconcile_sources.boundaries})
    res = CliRunner().invoke(main, ["reconcile", "--contract", pkg.contract,
                                    "--package", pkg.package,
                                    "--tests", str(_drift_dir(tmp_path))])
    assert res.exit_code == 0, res.output
    assert "OK: fix-sys@1.0.0" in res.output


def test_reconcile_incident_2_replay_exits_one(make_reconcile_pkg, reconcile_sources, tmp_path):
    pkg = make_reconcile_pkg({"boundaries.py": reconcile_sources.input_only})
    res = CliRunner().invoke(main, ["reconcile", "--contract", pkg.contract,
                                    "--package", pkg.package,
                                    "--tests", str(_drift_dir(tmp_path))])
    assert res.exit_code == 1
    assert "RECONCILE FAILED" in res.output
    assert "prompts_raw" in res.output


# ---- `contract events` (design 2026-07-24-event-log-reader-design.md) ----

def _log(tmp_path, records):
    import json
    p = tmp_path / "events.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in records))
    return p


def _ev(system="demo-consumer", boundary="prompts", schema="peec.prompts_export",
        version="1.0.0", result="pass"):
    return {"system": system, "boundary": boundary, "schema": schema, "version": version,
            "result": result,
            "observed_shape": {"columns": ["prompt"], "dtypes": {"prompt": "object"}},
            "timestamp": "2026-07-28T00:00:00Z"}


def test_events_human_output(tmp_path):
    log = _log(tmp_path, [_ev(result="pass"), _ev(result="violation")])
    res = CliRunner().invoke(main, ["events", "--log", str(log)])
    assert res.exit_code == 0, res.output
    assert "[blocked]" in res.output
    assert "peec.prompts_export@1.0.0" in res.output


def test_events_json_has_ready_and_skipped(tmp_path):
    import json
    log = _log(tmp_path, [_ev(result="pass")])
    res = CliRunner().invoke(main, ["events", "--log", str(log), "--json"])
    assert res.exit_code == 0, res.output
    doc = json.loads(res.output)
    assert doc["summary"]["ready"] is True
    assert doc["summary"]["skipped"] == 0
    assert doc["systems"][0]["boundaries"][0]["verdict"] == "clean"


def test_events_missing_log_is_not_an_error(tmp_path):
    res = CliRunner().invoke(main, ["events", "--log", str(tmp_path / "nope.jsonl")])
    assert res.exit_code == 0, res.output
    assert "no events recorded" in res.output.lower()


def test_events_unreadable_log_directory_fails(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    res = CliRunner().invoke(main, ["events", "--log", str(d)])
    assert res.exit_code == 1


def test_events_malformed_contract_fails(tmp_path):
    log = _log(tmp_path, [_ev()])
    res = CliRunner().invoke(main, ["events", "--log", str(log),
                                    "--contract", str(FIX / "contract_malformed.yaml")])
    assert res.exit_code == 1


def test_events_contract_flags_unobserved(tmp_path):
    # consumer/contract.yaml declares raw prompts_raw, input prompts, output report.
    log = _log(tmp_path, [_ev(boundary="prompts")])  # only 'prompts' fired
    res = CliRunner().invoke(main, ["events", "--log", str(log),
                                    "--contract", str(FIX / "consumer" / "contract.yaml")])
    assert res.exit_code == 0, res.output
    assert "[unobserved]" in res.output
    assert "report" in res.output  # the declared-but-unfired output boundary
