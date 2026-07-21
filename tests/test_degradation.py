# tests/test_degradation.py
from pathlib import Path

import pandas as pd
import pytest

from contract_core.errors import ContractViolation
from contract_core.runtime import ContractRuntime, _env_disabled, load_runtime

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


def _bad_df():
    """Data that WOULD hard-fail `peec.prompts_export@1.0.0` — `position` is missing."""
    return pd.DataFrame({"prompt": ["a"], "sentiment": [0.5], "share_of_voice": [0.3]})


def test_disabled_runtime_passes_data_through_untouched(monkeypatch):
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    rt = ContractRuntime.disabled()

    @rt.input("a-boundary-that-is-not-in-any-contract")
    def load():
        return _bad_df()

    out = load()
    assert list(out.columns) == ["prompt", "sentiment", "share_of_voice"]


def test_disabled_runtime_decorates_all_three_directions(monkeypatch):
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    rt = ContractRuntime.disabled()
    for deco in (rt.raw("x"), rt.input("x"), rt.output("x")):

        @deco
        def fn():
            return {"anything": 1}

        assert fn() == {"anything": 1}


def test_disabled_runtime_does_no_file_io(monkeypatch, tmp_path):
    # No contract read, no schema resolution, no event write (R9 design §3.3).
    events = tmp_path / "events.jsonl"
    monkeypatch.setenv("CONTRACT_EVENT_LOG", str(events))
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    rt = ContractRuntime.disabled()

    @rt.output("report")
    def emit():
        return {"nope": True}

    emit()
    assert not events.exists()


def test_disabled_warns_once_naming_trigger_and_label(monkeypatch, caplog):
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    with caplog.at_level("WARNING", logger="contract_core"):
        ContractRuntime.disabled("contract.yaml")
    warnings = [r for r in caplog.records if "DISABLED" in r.getMessage()]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == (
        "contract validation DISABLED (explicitly disabled) [contract.yaml]"
    )


def test_disabled_names_the_env_var_when_it_is_the_trigger(monkeypatch, caplog):
    monkeypatch.setenv("CONTRACT_DISABLED", "1")
    with caplog.at_level("WARNING", logger="contract_core"):
        ContractRuntime.disabled("contract.yaml")
    msg = caplog.records[-1].getMessage()
    assert msg == "contract validation DISABLED (CONTRACT_DISABLED set) [contract.yaml]"


def test_disabled_with_no_label_reads_unspecified(monkeypatch, caplog):
    # A disabled runtime does no file I/O, so it cannot read the contract to learn the
    # system name. It names what it actually has.
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    with caplog.at_level("WARNING", logger="contract_core"):
        ContractRuntime.disabled()
    assert "[unspecified]" in caplog.records[-1].getMessage()


FIX = Path(__file__).parent / "fixtures"
CONSUMER_CONTRACT = FIX / "consumer" / "contract.yaml"
SCHEMAS = FIX / "schemas"


def _enforcing_loader(rt):
    """A boundary whose data would hard-fail an enforcing runtime."""

    @rt.input("prompts")
    def load():
        return _bad_df()

    return load


def test_enabled_by_default_still_hard_fails_and_stays_quiet(
    monkeypatch, caplog, event_log_path
):
    # True negative: the toggle must not disable anything when nobody asked.
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    with caplog.at_level("WARNING", logger="contract_core"):
        rt = load_runtime(CONSUMER_CONTRACT, schema_paths=[SCHEMAS])
    with pytest.raises(ContractViolation):
        _enforcing_loader(rt)()
    assert not [r for r in caplog.records if "DISABLED" in r.getMessage()]


def test_env_var_set_to_zero_does_not_disable(monkeypatch, caplog, event_log_path):
    # The foot-gun case: an operator typing `0` must NOT disable the fleet.
    monkeypatch.setenv("CONTRACT_DISABLED", "0")
    with caplog.at_level("WARNING", logger="contract_core"):
        rt = load_runtime(CONSUMER_CONTRACT, schema_paths=[SCHEMAS])
    with pytest.raises(ContractViolation):
        _enforcing_loader(rt)()
    assert not [r for r in caplog.records if "DISABLED" in r.getMessage()]


def test_env_var_disables_and_warns(monkeypatch, caplog, event_log_path):
    monkeypatch.setenv("CONTRACT_DISABLED", "1")
    with caplog.at_level("WARNING", logger="contract_core"):
        rt = load_runtime(CONSUMER_CONTRACT, schema_paths=[SCHEMAS])
    assert _enforcing_loader(rt)() is not None  # returns its data, unchanged
    assert not event_log_path.exists()
    msg = caplog.records[-1].getMessage()
    assert msg == f"contract validation DISABLED (CONTRACT_DISABLED set) [{CONSUMER_CONTRACT}]"


def test_enabled_false_disables_and_warns(monkeypatch, caplog, event_log_path):
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    with caplog.at_level("WARNING", logger="contract_core"):
        rt = load_runtime(CONSUMER_CONTRACT, schema_paths=[SCHEMAS], enabled=False)
    assert _enforcing_loader(rt)() is not None
    assert not event_log_path.exists()
    assert "explicitly disabled" in caplog.records[-1].getMessage()


def test_off_always_wins_over_application_code(monkeypatch, caplog, event_log_path):
    # A module hardcoding enabled=True cannot defeat the ops kill switch (R9 design §3.3).
    monkeypatch.setenv("CONTRACT_DISABLED", "1")
    with caplog.at_level("WARNING", logger="contract_core"):
        rt = load_runtime(CONSUMER_CONTRACT, schema_paths=[SCHEMAS], enabled=True)
    assert _enforcing_loader(rt)() is not None
    assert "CONTRACT_DISABLED set" in caplog.records[-1].getMessage()


def test_disabled_factory_reads_no_contract_file(monkeypatch, tmp_path):
    # Proves "no file I/O": the path does not exist and construction still succeeds.
    monkeypatch.setenv("CONTRACT_DISABLED", "1")
    rt = load_runtime(tmp_path / "does-not-exist.yaml")
    assert rt.input("whatever")(lambda: 42)() == 42


def test_missing_contract_raises_when_enabled_no_auto_degrade(monkeypatch, tmp_path):
    # Fail-loud (design decision #3): a missing contract raises; it never silently disables.
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    with pytest.raises(FileNotFoundError):
        load_runtime(tmp_path / "does-not-exist.yaml")
