# tests/test_distribution.py
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Kept in step with tests/test_public_api.py::FROZEN_SURFACE by hand: this list is what a
# consumer's `from contract_core import ...` line looks like, and duplicating it here is
# deliberate — the whole point of the test is to prove that line works against a real install,
# so importing the expected names from the source tree would defeat it.
PUBLIC_NAMES = ["ContractRuntime", "ContractViolation", "FieldDiff", "load_runtime"]


def _run(*cmd: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([*cmd], capture_output=True, text=True, **kw)


def test_git_ref_install_exposes_the_public_api(tmp_path):
    """T1: `pip install "contract-core @ git+file://<repo>@<sha>"` then import the surface.

    A local file:// remote at a committed ref exercises the exact resolve-and-build-from-source
    path a consumer's `git+https://.../data-contract@vX.Y.Z` pin takes, with no deploy token.
    The *authenticated remote* half is verified once per release by the smoke test in
    docs/consuming-repo-setup.md — a tag cannot be installed before it is cut.

    Note this installs HEAD, the committed tree — not the working directory.
    """
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")

    head = _run("git", "-C", str(REPO), "rev-parse", "HEAD")
    assert head.returncode == 0, head.stderr
    sha = head.stdout.strip()

    venv = tmp_path / "venv"
    created = _run(sys.executable, "-m", "venv", str(venv))
    assert created.returncode == 0, created.stderr
    py = venv / "bin" / "python"

    # This test is about the git-ref resolve and the source build, NOT about re-resolving
    # pydantic/pandera/pandas from PyPI — so install --no-deps and borrow the runtime deps
    # from the outer (already installed) environment.
    #
    # `venv --system-site-packages` does NOT do that: it exposes the *base interpreter's*
    # site-packages, and when the test suite itself runs inside a venv (the normal case, and
    # in CI) that is not where the deps live. So name the running interpreter's purelib
    # explicitly via a .pth. A .pth is appended AFTER the new venv's own site-packages, which
    # matters: the outer env holds an editable-install shim `contract_core` that would
    # otherwise shadow the copy under test. The final assertion below pins that down.
    outer_purelib = sysconfig.get_paths()["purelib"]
    site_dir = _run(str(py), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])")
    assert site_dir.returncode == 0, site_dir.stderr
    (Path(site_dir.stdout.strip()) / "_outer_deps.pth").write_text(outer_purelib + "\n")

    spec = f"contract-core @ git+file://{REPO}@{sha}"
    installed = _run(str(py), "-m", "pip", "install", "--quiet", "--no-deps",
                     "--ignore-installed", spec)
    assert installed.returncode == 0, installed.stderr

    probe = (
        f"from contract_core import {', '.join(PUBLIC_NAMES)}\n"
        "import contract_core\n"
        "print(contract_core.__file__)\n"
    )
    imported = _run(str(py), "-c", probe)
    assert imported.returncode == 0, imported.stderr
    # Guard against a false green: the outer env is on sys.path for its deps, so assert the
    # import resolved to the copy we just built from the git ref, not to that outer env.
    assert str(venv) in imported.stdout, imported.stdout
