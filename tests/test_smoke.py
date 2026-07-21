# tests/test_smoke.py
from importlib.metadata import version

import contract_core


def test_package_imports_and_has_version():
    assert isinstance(contract_core.__version__, str)
    assert contract_core.__version__ != ""


def test_version_is_0_1_0():
    assert contract_core.__version__ == "0.1.0"


def test_version_matches_distribution_metadata():
    # `__version__` is on the frozen public surface (R9 design §3.2) but is hand-written in
    # __init__.py, while pip/consumers see pyproject's. A skew publishes a lie; fail here instead.
    assert contract_core.__version__ == version("contract-core")
