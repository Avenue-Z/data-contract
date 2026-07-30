"""Design §9.1: every template MUST carry a `.tmpl` extension, including the Python ones, so
neither ruff nor mypy considers them, and so `contract init` from a built wheel can find them
(design §9's "test asserts every template is present in the built wheel")."""
import subprocess
import sys
import tempfile
from pathlib import Path

TEMPLATES_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "contract_core" / "scaffold" / "templates"
)

EXPECTED = {
    "contract.mediated.yaml.tmpl",
    "contract.file-ingest.yaml.tmpl",
    "schema.payload.yaml.tmpl",
    "schema.tabular.yaml.tmpl",
    "boundaries.mediated.py.tmpl",
    "boundaries.file-ingest.py.tmpl",
    "drift_test.py.tmpl",
    "ci-workflow.mediated.yml.tmpl",
    "ci-workflow.file-ingest.yml.tmpl",
}


def test_every_expected_template_exists():
    actual = {p.name for p in TEMPLATES_DIR.iterdir()}
    assert actual == EXPECTED


def test_no_py_file_exists_under_templates():
    # A literal .py would be swept by ruff/mypy's first-party gates and fail them (design §9.1).
    assert not list(TEMPLATES_DIR.rglob("*.py"))


def test_templates_are_present_in_the_built_wheel():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        built = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(out)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True,
        )
        assert built.returncode == 0, built.stderr
        wheel = next(out.glob("*.whl"))
        listing = subprocess.run(
            [sys.executable, "-m", "zipfile", "-l", str(wheel)],
            capture_output=True, text=True,
        )
        assert listing.returncode == 0, listing.stderr
        for name in EXPECTED:
            assert f"contract_core/scaffold/templates/{name}" in listing.stdout, name
