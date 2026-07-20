# tests/test_runtime.py
import pandas as pd
import pytest
from contract_core.contract import Contract
from contract_core.errors import ContractViolation
from contract_core.events import EventLog
from contract_core.resolver import Resolver
from contract_core.runtime import ContractRuntime

from pathlib import Path
FIX = Path(__file__).parent / "fixtures"


def _runtime(tmp_path, mode="enforce"):
    contract = Contract.model_validate({
        "system": "demo", "version": "1.0.0",
        "inputs": [{"name": "prompts", "schema": "peec.prompts_export@1.0.0", "mode": mode}],
    })
    resolver = Resolver([FIX / "schemas"])
    log = EventLog(tmp_path / "events.jsonl")
    return ContractRuntime(contract, resolver, event_log=log,
                           clock=lambda: "2026-07-16T00:00:00+00:00"), log


def _good_df():
    return pd.DataFrame({
        "prompt": ["a"], "sentiment": [0.5],
        "position": pd.array([1], dtype="Int64"),
        "share_of_voice": [0.3],
    })


def test_enforce_passes_valid_data_and_logs(tmp_path):
    rt, log = _runtime(tmp_path)

    @rt.input("prompts")
    def load():
        return _good_df()

    out = load()
    assert list(out.columns) == ["prompt", "sentiment", "position", "share_of_voice"]
    assert log.records()[0]["result"] == "pass"


def test_enforce_extra_column_passes_open_input(tmp_path):
    rt, _ = _runtime(tmp_path)

    @rt.input("prompts")
    def load():
        df = _good_df()
        df["surprise_vendor_column"] = [1]
        return df

    load()  # must not raise — inputs are open


def test_enforce_missing_required_column_raises(tmp_path):
    rt, log = _runtime(tmp_path)

    @rt.input("prompts")
    def load():
        return _good_df().drop(columns=["position"])

    with pytest.raises(ContractViolation) as ei:
        load()
    assert "position" in str(ei.value)
    assert log.records()[-1]["result"] == "violation"


def test_observe_never_raises_but_logs_violation(tmp_path):
    rt, log = _runtime(tmp_path, mode="observe")

    @rt.input("prompts")
    def load():
        return _good_df().drop(columns=["position"])

    load()  # observe: no raise
    assert log.records()[-1]["result"] == "violation"


def test_registry_is_populated(tmp_path):
    from contract_core.runtime import ContractRuntime
    rt, _ = _runtime(tmp_path)

    @rt.input("prompts")
    def load():
        return _good_df()

    assert ("input", "prompts") in ContractRuntime.REGISTRY


def _payload_runtime(tmp_path, mode="enforce"):
    contract = Contract.model_validate({
        "system": "demo", "version": "1.0.0",
        "outputs": [{"name": "report", "schema": "aivx.report@1.0.0", "mode": mode}],
    })
    resolver = Resolver([FIX / "schemas"])
    log = EventLog(tmp_path / "e.jsonl")
    return ContractRuntime(contract, resolver, event_log=log,
                           clock=lambda: "2026-07-16T00:00:00+00:00"), log


def test_output_missing_field_raises(tmp_path):
    rt, _ = _payload_runtime(tmp_path)

    @rt.output("report")
    def produce():
        return {"slug": "digital-banks"}  # missing "score"

    with pytest.raises(ContractViolation):
        produce()


def test_output_extra_field_warns_not_raises(tmp_path):
    rt, log = _payload_runtime(tmp_path)

    @rt.output("report")
    def produce():
        return {"slug": "x", "score": 0.9, "debug_note": "hi"}

    produce()  # extra field must NOT raise
    assert log.records()[-1]["result"] == "warn"
