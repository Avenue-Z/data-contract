# tests/test_scaffold_apply.py
from pathlib import Path

from contract_core.scaffold.apply import apply
from contract_core.scaffold.plan import Plan, Target
from contract_core.scaffold.pyproject import MarkerAction


def _plan(
    root,
    contract_content="system: x\n",
    extra_targets=(),
    marker_action=MarkerAction.SATISFIED,
    pyproject_text="",
):
    return Plan(
        is_rerun=False, system="x", archetype="file-ingest",
        contract_target=Target(Path("contract.yaml"), contract_content, exists=False),
        other_targets=list(extra_targets),
        marker_action=marker_action, pyproject_text=pyproject_text,
        dependency_line="contract-core @ git+...", next_steps=[],
    )


def test_apply_writes_a_new_file_creating_parent_dirs(tmp_path):
    extra = Target(Path("schemas/p/n/1.0.0.yaml"), "schema: p.n\n", exists=False)
    apply(_plan(tmp_path, extra_targets=[extra]), tmp_path)
    assert (tmp_path / "contract.yaml").read_text() == "system: x\n"
    assert (tmp_path / "schemas/p/n/1.0.0.yaml").read_text() == "schema: p.n\n"


def test_apply_does_not_touch_a_target_marked_as_existing(tmp_path):
    (tmp_path / "contract.yaml").write_text("hand-authored\n")
    plan = _plan(tmp_path, contract_content="GENERATED\n")
    plan = Plan(**{**plan.__dict__, "contract_target": Target(
        Path("contract.yaml"), "GENERATED\n", exists=True
    )})
    apply(plan, tmp_path)
    assert (tmp_path / "contract.yaml").read_text() == "hand-authored\n"


def test_apply_inserts_the_marker_key_when_the_section_exists(tmp_path):
    pyproject = "[tool.pytest.ini_options]\npythonpath = [\"src\"]\n"
    plan = _plan(tmp_path, marker_action=MarkerAction.INSERT_KEY, pyproject_text=pyproject)
    apply(plan, tmp_path)
    text = (tmp_path / "pyproject.toml").read_text()
    assert "raw_drift" in text
    assert 'pythonpath = ["src"]' in text


def test_apply_does_not_touch_pyproject_toml_when_satisfied(tmp_path):
    original = "[tool.pytest.ini_options]\nmarkers = [\"raw_drift: x\"]\n"
    (tmp_path / "pyproject.toml").write_text(original)
    apply(_plan(tmp_path, marker_action=MarkerAction.SATISFIED), tmp_path)
    assert (tmp_path / "pyproject.toml").read_text() == original


def test_apply_does_not_touch_pyproject_toml_when_manual(tmp_path):
    original = "[tool.pytest.ini_options]\nmarkers = [\"other: x\"]\n"
    (tmp_path / "pyproject.toml").write_text(original)
    apply(_plan(tmp_path, marker_action=MarkerAction.MANUAL), tmp_path)
    assert (tmp_path / "pyproject.toml").read_text() == original


def test_apply_writes_nothing_when_the_marker_edit_cannot_be_applied(tmp_path):
    """A raise from `apply_marker` leaves the tree untouched: the marker edit is computed from the
    plan's pyproject snapshot BEFORE any file is written, so nothing partial lands. (The multi-file
    loop itself is not transactional — see apply()'s comment — but the pre-write raise is.)"""
    import pytest

    # A pyproject with no `[tool.pytest.ini_options]` header line — apply_marker(INSERT_KEY) raises.
    pyproject = "[tool.ruff]\nline-length = 100\n"
    extra = Target(Path("schemas/p/n/1.0.0.yaml"), "schema: p.n\n", exists=False)
    plan = _plan(tmp_path, extra_targets=[extra], marker_action=MarkerAction.INSERT_KEY,
                 pyproject_text=pyproject)
    with pytest.raises(ValueError):
        apply(plan, tmp_path)
    assert not (tmp_path / "contract.yaml").exists()
    assert not (tmp_path / "schemas").exists()


def test_apply_is_idempotent_over_two_calls(tmp_path):
    extra = Target(Path("schemas/p/n/1.0.0.yaml"), "schema: p.n\n", exists=False)
    plan = _plan(tmp_path, extra_targets=[extra])
    apply(plan, tmp_path)
    apply(plan, tmp_path)  # simulates dry-run-then-real-run against the same Plan
    assert (tmp_path / "schemas/p/n/1.0.0.yaml").read_text() == "schema: p.n\n"
