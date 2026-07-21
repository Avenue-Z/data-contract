# tests/test_degradation.py
import pandas as pd
import pytest

from contract_core.runtime import ContractRuntime, _env_disabled

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
