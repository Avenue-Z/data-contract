# tests/test_smoke.py
import tomllib
from pathlib import Path

import contract_core


def test_package_imports_and_has_version():
    assert isinstance(contract_core.__version__, str)
    assert contract_core.__version__ != ""


def test_version_matches_pyproject():
    # `__version__` is on the frozen public surface (R9 design §3.2) but is hand-written in
    # __init__.py, while pip/consumers see pyproject's. A skew publishes a lie; fail here instead.
    #
    # Read pyproject directly rather than `importlib.metadata.version`: installed metadata is a
    # snapshot taken at install time, so on a dev machine with a stale editable install this
    # would compare `__init__.py` against a version nobody is shipping and pass on a real skew.
    # This is also why the release procedure names exactly two files — these two.
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert contract_core.__version__ == declared
