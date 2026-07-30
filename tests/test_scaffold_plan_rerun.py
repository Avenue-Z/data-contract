from pathlib import Path

from contract_core.contract import BoundarySpec, Contract
from contract_core.scaffold.plan import InitSpec, plan, render_report
from contract_core.scaffold.pyproject import MarkerAction

ROOT = Path("/repo")


def _existing_spec(contract: Contract, existing_pyproject="[tool.ruff]\nline-length = 100\n"):
    return InitSpec(
        root=ROOT, package="my_pkg", package_dir=ROOT / "src" / "my_pkg",
        pyproject_text=existing_pyproject, contract_core_version="0.7.0",
        fresh=None, existing=contract,
    )


def _mediated_contract():
    return Contract(
        format_version="v1", system="tiktok-brand-pulse", version="0.1.0",
        raw=[BoundarySpec(name="tiktok_raw", schema="tiktok.raw_report@1", mode="observe")],
        inputs=[BoundarySpec(name="records", schema="tiktok.records@1", mode="observe")],
        outputs=[BoundarySpec(name="report", schema="tiktok.report@1", mode="observe")],
    )


def test_archetype_is_derived_from_raw_non_empty():
    result = plan(_existing_spec(_mediated_contract()), existing_paths={Path("contract.yaml")})
    assert result.archetype == "mediated"
    assert result.is_rerun is True


def test_file_ingest_when_raw_is_empty():
    contract = Contract(
        format_version="v1", system="sentiment-digest", version="0.1.0",
        inputs=[BoundarySpec(name="scores", schema="sentiment.scores@1", mode="observe")],
        outputs=[BoundarySpec(name="digest", schema="sentiment.digest@1", mode="observe")],
    )
    result = plan(_existing_spec(contract), existing_paths={Path("contract.yaml")})
    assert result.archetype == "file-ingest"


def test_a_hand_renamed_boundary_drives_the_gap_filled_schema_path():
    contract = Contract(
        format_version="v1", system="tiktok-brand-pulse", version="0.1.0",
        raw=[BoundarySpec(name="tiktok_raw", schema="tiktok.raw_report@1", mode="observe")],
        inputs=[BoundarySpec(name="campaign_metrics", schema="tiktok.campaign_metrics@1",
                              mode="observe")],
        outputs=[BoundarySpec(name="report", schema="brandpulse.report@1", mode="observe")],
    )
    result = plan(_existing_spec(contract), existing_paths={Path("contract.yaml")})
    paths = {t.path for t in result.other_targets}
    assert Path("schemas/tiktok/campaign_metrics/1.0.0.yaml") in paths
    assert Path("schemas/brandpulse/report/1.0.0.yaml") in paths


def test_exact_pin_gap_fills_to_the_matching_filename_and_version_body():
    contract = Contract(
        format_version="v1", system="sys", version="0.1.0",
        inputs=[BoundarySpec(name="records", schema="tiktok.records@1.2.3", mode="observe")],
        outputs=[BoundarySpec(name="report", schema="tiktok.report@1", mode="observe")],
    )
    result = plan(_existing_spec(contract), existing_paths={Path("contract.yaml")})
    target = next(
        t for t in result.other_targets if t.path == Path("schemas/tiktok/records/1.2.3.yaml")
    )
    assert "version: 1.2.3" in target.content


def test_gap_fill_declines_when_the_schema_directory_already_holds_a_semver_file():
    contract = Contract(
        format_version="v1", system="sys", version="0.1.0",
        raw=[BoundarySpec(name="raw", schema="tiktok.raw_report@1", mode="observe")],
        inputs=[BoundarySpec(name="records", schema="tiktok.records@1", mode="observe")],
        outputs=[BoundarySpec(name="report", schema="tiktok.report@1", mode="observe")],
    )
    existing = {
        Path("contract.yaml"),
        Path("schemas/tiktok/records/2.0.0.yaml"),  # promoted past @1 — a real, author-owned file
    }
    result = plan(_existing_spec(contract), existing_paths=existing)
    target = next(
        t for t in result.other_targets if t.path == Path("schemas/tiktok/records/1.0.0.yaml")
    )
    assert target.status == "skipped"
    assert target.skip_reason == "schema directory not empty"


def test_gap_fill_ignores_non_semver_strays_in_the_schema_directory():
    contract = Contract(
        format_version="v1", system="sys", version="0.1.0",
        inputs=[BoundarySpec(name="records", schema="tiktok.records@1", mode="observe")],
        outputs=[BoundarySpec(name="report", schema="tiktok.report@1", mode="observe")],
    )
    existing = {Path("contract.yaml"), Path("schemas/tiktok/records/_template.yaml")}
    result = plan(_existing_spec(contract), existing_paths=existing)
    target = next(
        t for t in result.other_targets if t.path == Path("schemas/tiktok/records/1.0.0.yaml")
    )
    assert target.status == "created"


def test_a_second_run_over_a_fully_scaffolded_tree_writes_nothing():
    contract = _mediated_contract()
    all_paths = {
        Path("contract.yaml"),
        Path("schemas/tiktok/raw_report/1.0.0.yaml"),
        Path("schemas/tiktok/records/1.0.0.yaml"),
        Path("schemas/tiktok/report/1.0.0.yaml"),
        Path("src/my_pkg/boundaries.py"),
        Path("tests/test_drift_tiktok_raw.py"),
        Path(".github/workflows/contract.yml"),
    }
    text = (
        "[tool.pytest.ini_options]\n"
        'markers = ["raw_drift: a drift test guarding a raw boundary"]\n'
    )
    result = plan(_existing_spec(contract, existing_pyproject=text), existing_paths=all_paths)
    assert all(t.status == "skipped" for t in result.other_targets)
    assert result.marker_action == MarkerAction.SATISFIED


def test_rerun_report_leads_with_a_read_line_not_a_created_or_skipped_line():
    contract = _mediated_contract()
    result = plan(_existing_spec(contract), existing_paths={Path("contract.yaml")})
    lines = render_report(result)
    assert lines[0] == "read      contract.yaml (tiktok-brand-pulse, mediated)"
    assert not any("contract.yaml" in line and line is not lines[0] for line in lines[1:])
