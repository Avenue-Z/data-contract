# tests/test_smoke.py
import contract_core


def test_package_imports_and_has_version():
    assert isinstance(contract_core.__version__, str)
    assert contract_core.__version__ != ""
