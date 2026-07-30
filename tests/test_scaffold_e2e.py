"""End-to-end scaffold tests (design 2026-07-30 §10). Subprocess, not in-process: `reconcile`
mutates sys.modules, and the console script is the supported entry point — the same reasoning
tests/test_distribution.py already uses.
"""
import subprocess
import sys
from pathlib import Path

import pytest


def _run(*cmd: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    import os
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(cmd, cwd=cwd, env=full_env, capture_output=True, text=True)


def _scaffold_repo(tmp_path: Path, pkg: str = "my_pkg") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "{pkg}"\n')
    (tmp_path / pkg).mkdir()
    (tmp_path / pkg / "__init__.py").write_text("")
    return tmp_path


def _pythonpath_for(root: Path, pkg_dir_parent: Path) -> str:
    # design §10.1: a console script's sys.path[0] is the script's own dir, not cwd — PYTHONPATH
    # must name the directory CONTAINING the package directory, src/ for a src layout, root for
    # flat.
    return str(pkg_dir_parent)


@pytest.mark.parametrize("source_kind,archetype", [("api", "mediated"), ("file", "file-ingest")])
def test_scaffolded_tree_lints_and_reconciles_clean(tmp_path, source_kind, archetype):
    root = _scaffold_repo(tmp_path)
    init = _run(
        "contract", "init", "--root", str(root), "--system", "sys",
        "--platform", "plat", "--source", source_kind, cwd=root,
    )
    assert init.returncode == 0, init.stdout + init.stderr

    lint = _run("contract", "lint", "--contract", "contract.yaml", "--schemas", "schemas",
                cwd=root)
    assert lint.returncode == 0, lint.stdout + lint.stderr

    reconcile = _run(
        "contract", "reconcile", "--contract", "contract.yaml", "--package", "my_pkg",
        "--tests", "tests", cwd=root, env={"PYTHONPATH": _pythonpath_for(root, root)},
    )
    assert reconcile.returncode == 0, reconcile.stdout + reconcile.stderr


def test_rerun_is_a_fixed_point(tmp_path):
    root = _scaffold_repo(tmp_path)
    first = _run("contract", "init", "--root", str(root), "--system", "sys",
                 "--platform", "plat", "--source", "api", cwd=root)
    assert first.returncode == 0, first.stdout + first.stderr
    second = _run("contract", "init", "--root", str(root), cwd=root)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "read      contract.yaml" in second.stdout


def test_dry_run_makes_zero_filesystem_mutations(tmp_path):
    root = _scaffold_repo(tmp_path)
    before = sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file())
    result = _run("contract", "init", "--root", str(root), "--system", "sys",
                  "--platform", "plat", "--source", "api", "--dry-run", cwd=root)
    assert result.returncode == 0, result.stdout + result.stderr
    after = sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file())
    assert before == after


def test_platform_with_a_dot_exits_nonzero_and_writes_nothing(tmp_path):
    root = _scaffold_repo(tmp_path)
    result = _run("contract", "init", "--root", str(root), "--system", "sys",
                  "--platform", "google.ads", "--source", "api", cwd=root)
    assert result.returncode != 0
    assert not (root / "contract.yaml").exists()


def test_platform_with_a_slash_exits_nonzero_and_writes_nothing(tmp_path):
    root = _scaffold_repo(tmp_path)
    result = _run("contract", "init", "--root", str(root), "--system", "sys",
                  "--platform", "a/b", "--source", "api", cwd=root)
    assert result.returncode != 0
    assert not (root / "contract.yaml").exists()


def test_platform_with_a_hyphen_lints_clean(tmp_path):
    root = _scaffold_repo(tmp_path)
    init = _run("contract", "init", "--root", str(root), "--system", "sys",
               "--platform", "foo-bar", "--source", "file", cwd=root)
    assert init.returncode == 0, init.stdout + init.stderr
    lint = _run("contract", "lint", "--contract", "contract.yaml", "--schemas", "schemas",
                cwd=root)
    assert lint.returncode == 0, lint.stdout + lint.stderr


def test_both_layouts_present_exits_nonzero_and_names_both(tmp_path):
    root = _scaffold_repo(tmp_path)
    (root / "src" / "my_pkg").mkdir(parents=True)
    (root / "src" / "my_pkg" / "__init__.py").write_text("")
    result = _run("contract", "init", "--root", str(root), "--system", "sys",
                  "--platform", "plat", "--source", "api", cwd=root)
    assert result.returncode != 0
    assert "my_pkg" in result.stdout


def test_no_package_exits_nonzero_and_names_the_flag(tmp_path):
    root = tmp_path
    (root / "pyproject.toml").write_text('[project]\nname = "my-pkg"\n')
    result = _run("contract", "init", "--root", str(root), "--system", "sys",
                  "--platform", "plat", "--source", "api", cwd=root)
    assert result.returncode != 0
    assert "--package" in result.stdout


def test_generated_mode_is_observe_for_every_boundary(tmp_path):
    root = _scaffold_repo(tmp_path)
    _run("contract", "init", "--root", str(root), "--system", "sys", "--platform", "plat",
         "--source", "api", cwd=root)
    content = (root / "contract.yaml").read_text()
    assert content.count("mode: observe") == 3
    assert "mode: enforce" not in content


def test_contract_is_loadable_and_version_is_0_1_0(tmp_path):
    from contract_core.contract import Contract
    root = _scaffold_repo(tmp_path)
    _run("contract", "init", "--root", str(root), "--system", "sys", "--platform", "plat",
         "--source", "api", cwd=root)
    contract = Contract.from_yaml(root / "contract.yaml")
    assert contract.version == "0.1.0"


def test_drift_job_present_for_mediated_absent_for_file_ingest(tmp_path):
    mediated = _scaffold_repo(tmp_path / "mediated", pkg="pkg_m")
    _run("contract", "init", "--root", str(mediated), "--system", "sys", "--platform", "plat",
         "--source", "api", cwd=mediated)
    assert "drift:" in (mediated / ".github/workflows/contract.yml").read_text()

    file_ingest_root = _scaffold_repo(tmp_path / "file_ingest", pkg="pkg_f")
    _run("contract", "init", "--root", str(file_ingest_root), "--system", "sys",
         "--platform", "plat", "--source", "file", cwd=file_ingest_root)
    workflow = (file_ingest_root / ".github/workflows/contract.yml").read_text()
    assert "drift:" not in workflow


def test_no_secret_emitted(tmp_path):
    root = _scaffold_repo(tmp_path)
    _run("contract", "init", "--root", str(root), "--system", "sys", "--platform", "plat",
         "--source", "api", cwd=root)
    workflow = (root / ".github/workflows/contract.yml").read_text()
    assert "secrets:" not in workflow


def test_drift_stub_is_red_not_a_collection_error(tmp_path):
    root = _scaffold_repo(tmp_path)
    _run("contract", "init", "--root", str(root), "--system", "sys", "--platform", "plat",
         "--source", "api", cwd=root)
    result = _run(sys.executable, "-m", "pytest", "-m", "raw_drift", cwd=root,
                  env={"PYTHONPATH": str(root)})
    # not green, not "no tests collected"
    assert result.returncode not in (0, 5), result.stdout + result.stderr
    assert "GENERATED PLACEHOLDER" in result.stdout
