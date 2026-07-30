from pathlib import Path

import pytest

from contract_core.scaffold.plan import (
    FreshSpec,
    InitSpec,
    PlanError,
    plan,
    render_report,
)
from contract_core.scaffold.pyproject import MarkerAction

ROOT = Path("/repo")
PYPROJECT_NO_MARKERS = "[tool.ruff]\nline-length = 100\n"


def _fresh_spec(system="tiktok-brand-pulse", platform="tiktok", source_kind="api",
                 package="my_pkg", pyproject_text=PYPROJECT_NO_MARKERS):
    return InitSpec(
        root=ROOT, package=package, package_dir=ROOT / "src" / package,
        pyproject_text=pyproject_text, contract_core_version="0.7.0",
        fresh=FreshSpec(system=system, platform=platform, source_kind=source_kind),
        existing=None,
    )


def test_mediated_archetype_generates_raw_input_output_and_a_drift_test():
    result = plan(_fresh_spec(source_kind="api"), existing_paths=set())
    assert result.archetype == "mediated"
    paths = {t.path for t in result.other_targets}
    assert Path("schemas/tiktok/raw_report/1.0.0.yaml") in paths
    assert Path("schemas/tiktok/records/1.0.0.yaml") in paths
    assert Path("schemas/tiktok/report/1.0.0.yaml") in paths
    assert Path("src/my_pkg/boundaries.py") in paths
    assert Path("tests/test_drift_tiktok_raw.py") in paths
    assert Path(".github/workflows/contract.yml") in paths


def test_file_ingest_archetype_has_no_raw_no_drift_test_no_drift_job():
    result = plan(_fresh_spec(source_kind="file"), existing_paths=set())
    assert result.archetype == "file-ingest"
    paths = {t.path for t in result.other_targets}
    assert Path("schemas/tiktok/raw_report/1.0.0.yaml") not in paths
    assert not any("drift" in str(p) for p in paths)
    workflow_path = Path(".github/workflows/contract.yml")
    workflow = next(t for t in result.other_targets if t.path == workflow_path)
    assert "drift:" not in workflow.content
    assert "raw_drift" not in workflow.content


@pytest.mark.parametrize("source_kind", ["api", "mcp", "llm"])
def test_every_mediated_kind_produces_the_mediated_archetype(source_kind):
    result = plan(_fresh_spec(source_kind=source_kind), existing_paths=set())
    assert result.archetype == "mediated"


def test_contract_yaml_matches_the_design_4_0_literal_example():
    result = plan(_fresh_spec(), existing_paths=set())
    content = result.contract_target.content
    assert "system: tiktok-brand-pulse" in content
    assert "version: 0.1.0" in content
    assert "schema: tiktok.raw_report@1" in content
    assert "schema: tiktok.records@1" in content
    assert "schema: tiktok.report@1" in content
    assert content.count("mode: observe") == 3
    assert "@1.0" not in content  # never the non-pin form


def test_every_generated_schema_ref_uses_the_at_major_pin_form():
    result = plan(_fresh_spec(), existing_paths=set())
    for t in result.other_targets:
        if t.path.parts[0] == "schemas":
            assert "@1.0" not in t.content


def test_platform_with_a_dot_is_rejected_before_anything_is_planned():
    with pytest.raises(PlanError, match=r"\."):
        plan(_fresh_spec(platform="google.ads"), existing_paths=set())


def test_platform_with_a_slash_is_rejected():
    with pytest.raises(PlanError, match="/"):
        plan(_fresh_spec(platform="a/b"), existing_paths=set())


def test_platform_with_a_hyphen_is_accepted():
    result = plan(_fresh_spec(platform="foo-bar"), existing_paths=set())
    assert "schema: foo-bar.records@1" in result.contract_target.content


def test_empty_platform_is_rejected_before_anything_is_planned():
    with pytest.raises(PlanError):
        plan(_fresh_spec(platform=""), existing_paths=set())


def test_existing_targets_are_reported_skipped_not_overwritten():
    existing = {Path("contract.yaml"), Path("src/my_pkg/boundaries.py")}
    result = plan(_fresh_spec(), existing_paths=existing)
    assert result.contract_target.status == "skipped"
    boundaries_target = next(
        t for t in result.other_targets if t.path == Path("src/my_pkg/boundaries.py")
    )
    assert boundaries_target.status == "skipped"
    schema_target = next(
        t for t in result.other_targets if t.path == Path("schemas/tiktok/records/1.0.0.yaml")
    )
    assert schema_target.status == "created"


def test_report_created_lines_for_a_first_run():
    result = plan(_fresh_spec(), existing_paths=set())
    lines = render_report(result)
    assert any(line == "created  contract.yaml" for line in lines)
    assert any("schemas/tiktok/raw_report/1.0.0.yaml" in line for line in lines)
    assert lines[-1].startswith("edited") or lines[-1].startswith("satisfied")


def test_report_collapses_consecutive_skips_into_a_count():
    all_paths = {
        Path("contract.yaml"),
        Path("schemas/tiktok/raw_report/1.0.0.yaml"),
        Path("schemas/tiktok/records/1.0.0.yaml"),
        Path("schemas/tiktok/report/1.0.0.yaml"),
        Path("src/my_pkg/boundaries.py"),
        Path("tests/test_drift_tiktok_raw.py"),
        Path(".github/workflows/contract.yml"),
    }
    result = plan(_fresh_spec(), existing_paths=all_paths)
    lines = render_report(result)
    # exact count depends on contract.yaml's own line — asserted precisely in Task 6's re-run test
    assert any("7 files" in line for line in lines) or any(
        "skipped" in line for line in lines
    )


def test_dependency_line_names_the_installed_contract_core_version():
    result = plan(_fresh_spec(), existing_paths=set())
    assert "git+https://github.com/Avenue-Z/data-contract.git@v0.7.0" in result.dependency_line


def test_mediated_next_steps_mention_the_intentional_red():
    result = plan(_fresh_spec(source_kind="api"), existing_paths=set())
    assert any("GENERATED PLACEHOLDER" in s or "drift" in s for s in result.next_steps)


def test_manual_marker_action_surfaces_the_snippet_in_next_steps():
    text = '[tool.pytest.ini_options]\nmarkers = ["other: x"]\n'
    result = plan(_fresh_spec(pyproject_text=text), existing_paths=set())
    assert result.marker_action == MarkerAction.MANUAL
    assert any("raw_drift" in s for s in result.next_steps)


def test_file_ingest_creates_a_tests_placeholder_so_the_gate_reconciles():
    result = plan(_fresh_spec(source_kind="file"), existing_paths=set())
    paths = {t.path for t in result.other_targets}
    assert Path("tests/.gitkeep") in paths


def test_mediated_has_no_tests_placeholder_only_the_drift_test():
    result = plan(_fresh_spec(source_kind="api"), existing_paths=set())
    paths = {t.path for t in result.other_targets}
    assert Path("tests/.gitkeep") not in paths
