# tests/test_degradation.py
import pytest

from contract_core.runtime import _env_disabled

# The pinned truth table (R9 design §3.3). An operator typing `0` or `false` must NOT
# accidentally disable every contract in the fleet, so those are OFF values, not "truthy".
ON_VALUES = ["1", "true", "TRUE", "yes", "on", "  1  ", "disabled", "please"]
OFF_VALUES = ["", "0", "false", "FALSE", "no", "No", "  0  "]


@pytest.mark.parametrize("value", ON_VALUES)
def test_env_disabled_is_on_for(value, monkeypatch):
    monkeypatch.setenv("CONTRACT_DISABLED", value)
    assert _env_disabled() is True


@pytest.mark.parametrize("value", OFF_VALUES)
def test_env_disabled_is_off_for(value, monkeypatch):
    monkeypatch.setenv("CONTRACT_DISABLED", value)
    assert _env_disabled() is False


def test_env_disabled_is_off_when_unset(monkeypatch):
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    assert _env_disabled() is False
