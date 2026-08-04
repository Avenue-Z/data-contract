# tests/test_runtime.py
from pathlib import Path

import pandas as pd
import pytest

from contract_core.contract import Contract
from contract_core.errors import ContractViolation
from contract_core.events import EventLog
from contract_core.resolver import Resolver
from contract_core.runtime import ContractRuntime

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
    rec = log.records()[-1]
    assert rec["result"] == "violation"
    # observed_shape stays the structural shape dict on a violation (regression:
    # the per-field dtype string must not overwrite it).
    assert rec["observed_shape"]["columns"] == ["prompt", "sentiment", "share_of_voice"]
    assert "dtypes" in rec["observed_shape"]


def test_enforce_type_change_raises_retyped_naming_field(tmp_path):
    # R8 regression: family-based dtype validation must still hard-fail a genuine
    # type change, surfacing it as a `retyped` diff naming the field and its dtype.
    rt, log = _runtime(tmp_path)

    @rt.input("prompts")
    def load():
        df = _good_df()
        df["position"] = df["position"].astype(str)  # vendor sends strings, not ints
        return df

    with pytest.raises(ContractViolation) as ei:
        load()
    assert "position" in str(ei.value)
    assert "retyped" in str(ei.value)
    assert "expected int" in str(ei.value)
    assert log.records()[-1]["result"] == "violation"


def test_enforce_inferred_equivalent_dtype_passes(tmp_path):
    # R8 core: a plain int64 for a declared int (Int64) is not drift — must pass.
    rt, log = _runtime(tmp_path)

    @rt.input("prompts")
    def load():
        df = _good_df()
        df["position"] = df["position"].astype("int64")  # plain int64, not Int64
        return df

    load()  # must not raise
    assert log.records()[-1]["result"] == "pass"


def test_enforce_null_in_non_nullable_column_labeled_nullable_not_retyped(tmp_path):
    # A null in a non-nullable column (`prompt`) is a null-tolerance violation,
    # not a type change: it must surface as `nullable`, not a mislabeled `retyped`
    # with the (valid) dtype as observed.
    rt, log = _runtime(tmp_path)

    @rt.input("prompts")
    def load():
        df = _good_df()
        df["prompt"] = [None]  # non-nullable field, now all-null
        return df

    with pytest.raises(ContractViolation) as ei:
        load()
    msg = str(ei.value)
    assert "nullable field 'prompt'" in msg
    assert "retyped field 'prompt'" not in msg
    assert log.records()[-1]["result"] == "violation"


def test_enforce_column_both_retyped_and_null_bearing_reports_both(tmp_path):
    # #22: a column that is BOTH wrongly typed and null-bearing under nullable: false must
    # surface two structural diffs (retyped AND nullable). Keying structural diffs by field
    # alone collapses to one — the operator fixes the dtype, re-runs, and only then learns of
    # the null problem. Value diffs already keep distinct facts per (field, check); match that.
    rt, _ = _runtime(tmp_path)

    @rt.input("prompts")
    def load():
        # `prompt` is the only non-nullable field; send it as Int64 (wrong family, expected str)
        # carrying a null, so both the dtype-family check and the not-null check fire on it.
        return pd.DataFrame({
            "prompt": pd.array([1, None], dtype="Int64"),
            "sentiment": [0.5, 0.6],
            "position": pd.array([1, 2], dtype="Int64"),
            "share_of_voice": [0.3, 0.4],
        })

    with pytest.raises(ContractViolation) as ei:
        load()
    msg = str(ei.value)
    assert "retyped field 'prompt'" in msg
    assert "nullable field 'prompt'" in msg


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

    assert ("demo", "input", "prompts") in ContractRuntime.REGISTRY


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


# ---- wrong-type returns (F1) ----
#
# observe is the adoption on-ramp and is documented as "never fail the job", so a forgotten
# `return` (None) or a producer handing back a dict must log, not crash. Before the guard,
# `_validate_tabular`/`_validate_payload` reached for `.columns`/`.keys()` and raised a raw
# AttributeError in EVERY mode.


@pytest.mark.parametrize("bad", [None, {"a": 1}, [1, 2], "text"])
def test_tabular_wrong_type_return_does_not_crash_observe(tmp_path, bad):
    rt, log = _runtime(tmp_path, mode="observe")

    @rt.input("prompts")
    def load():
        return bad

    assert load() is bad  # the job survives and its value passes through untouched
    rec = log.records()[-1]
    assert rec["result"] == "violation"
    assert rec["observed_shape"] == {"type": type(bad).__name__}


def test_tabular_wrong_type_return_raises_contract_violation_under_enforce(tmp_path):
    rt, _ = _runtime(tmp_path, mode="enforce")

    @rt.input("prompts")
    def load():
        return None

    with pytest.raises(ContractViolation) as ei:
        load()
    diff = ei.value.diffs[0]
    assert (diff.field, diff.problem) == ("<return>", "retyped")
    assert (diff.expected, diff.observed) == ("dataframe", "NoneType")


@pytest.mark.parametrize("bad", [None, [1, 2], "text", 42])
def test_payload_wrong_type_return_does_not_crash_observe(tmp_path, bad):
    rt, log = _payload_runtime(tmp_path, mode="observe")

    @rt.output("report")
    def produce():
        return bad

    assert produce() is bad
    assert log.records()[-1]["result"] == "violation"


def test_payload_wrong_type_return_raises_contract_violation_under_enforce(tmp_path):
    rt, _ = _payload_runtime(tmp_path, mode="enforce")

    @rt.output("report")
    def produce():
        return [1, 2]

    with pytest.raises(ContractViolation) as ei:
        produce()
    diff = ei.value.diffs[0]
    assert (diff.field, diff.problem) == ("<return>", "retyped")
    assert (diff.expected, diff.observed) == ("object", "list")


# ---- payload temporal values (F2) ----
#
# `date`/`datetime` compile to `format`, and JSON Schema `format` is annotation-only unless
# the validator is given a format checker — so "not-a-date" used to pass a payload boundary
# silently, asymmetric with the tabular path's real datetime dtype.


def _temporal_runtime(tmp_path, mode="enforce"):
    contract = Contract.model_validate({
        "system": "demo", "version": "1.0.0",
        "outputs": [{"name": "stamped", "schema": "aivx.temporal@1.0.0", "mode": mode}],
    })
    log = EventLog(tmp_path / "e.jsonl")
    return ContractRuntime(contract, Resolver([FIX / "schemas"]), event_log=log,
                           clock=lambda: "2026-07-16T00:00:00+00:00"), log


def test_payload_valid_temporal_values_pass(tmp_path):
    rt, log = _temporal_runtime(tmp_path)

    @rt.output("stamped")
    def produce():
        return {"day": "2026-07-16", "at": "2026-07-16T09:30:00Z"}

    produce()
    assert log.records()[-1]["result"] == "pass"


@pytest.mark.parametrize("field,payload", [
    ("day", {"day": "not-a-date", "at": "2026-07-16T09:30:00Z"}),
    ("at", {"day": "2026-07-16", "at": "also-not-a-datetime"}),
])
def test_payload_malformed_temporal_value_is_a_violation(tmp_path, field, payload):
    rt, _ = _temporal_runtime(tmp_path)

    @rt.output("stamped")
    def produce():
        return payload

    with pytest.raises(ContractViolation) as ei:
        produce()
    diff = ei.value.diffs[0]
    assert (diff.field, diff.problem) == (field, "value")
    assert diff.constraint == f"format={'date' if field == 'day' else 'date-time'}"


def _raw_temporal_runtime(tmp_path):
    contract = Contract.model_validate({
        "system": "demo", "version": "1.0.0",
        "outputs": [{"name": "person", "schema": "aivx.raw_temporal@1.0.0", "mode": "enforce"}],
    })
    log = EventLog(tmp_path / "e.jsonl")
    return ContractRuntime(contract, Resolver([FIX / "schemas"]), event_log=log,
                           clock=lambda: "2026-07-16T00:00:00+00:00"), log


def test_raw_json_schema_temporal_format_is_checked_too(tmp_path):
    # The checker hangs off the payload validator, so it reaches a hand-authored
    # `format: date` as well — a raw-schema author sees new failures on this pin, and the
    # CHANGELOG says so. Pinned here so that disclosure cannot quietly stop being true.
    rt, _ = _raw_temporal_runtime(tmp_path)

    @rt.output("person")
    def produce():
        return {"born": "NOPE", "email": "someone@example.com"}

    with pytest.raises(ContractViolation) as ei:
        produce()
    diff = ei.value.diffs[0]
    assert (diff.field, diff.problem, diff.constraint) == ("born", "value", "format=date")


def test_raw_json_schema_email_format_stays_annotation_only(tmp_path):
    # The other half of the same disclosure: F2 is scoped to temporal on purpose, so a raw
    # schema declaring `format: email` must NOT start failing.
    rt, log = _raw_temporal_runtime(tmp_path)

    @rt.output("person")
    def produce():
        return {"born": "2026-07-16", "email": "not-an-email"}

    produce()
    assert log.records()[-1]["result"] == "pass"


# ---- raw `json_schema` payloads on a closed output (F5) ----


def _raw_payload_runtime(tmp_path, mode="enforce"):
    contract = Contract.model_validate({
        "system": "demo", "version": "1.0.0",
        "outputs": [{"name": "raw_out", "schema": "aivx.raw@1.0.0", "mode": mode}],
        "inputs": [{"name": "raw_in", "schema": "aivx.raw@1.0.0", "mode": mode}],
    })
    log = EventLog(tmp_path / "e.jsonl")
    return ContractRuntime(contract, Resolver([FIX / "schemas"]), event_log=log,
                           clock=lambda: "2026-07-16T00:00:00+00:00"), log


def test_raw_json_schema_payload_extra_key_warns_on_output(tmp_path):
    # A fields-based payload already warns here. `to_json_schema` returned a raw schema
    # verbatim and ignored `open`, so `additionalProperties` was absent, extras were
    # allowed, and no warn ever fired.
    rt, log = _raw_payload_runtime(tmp_path)

    @rt.output("raw_out")
    def produce():
        return {"slug": "x", "debug_note": "hi"}

    produce()  # extras on an output warn, they never raise
    rec = log.records()[-1]
    assert rec["result"] == "warn"


def test_raw_json_schema_payload_extra_key_passes_on_input(tmp_path):
    rt, log = _raw_payload_runtime(tmp_path)

    @rt.input("raw_in")
    def load():
        return {"slug": "x", "vendor_surprise": 1}

    load()
    assert log.records()[-1]["result"] == "pass"


def test_composition_payload_does_not_warn_on_a_valid_output(tmp_path):
    # The end-to-end shape of the compiler skip: a `oneOf` payload declares `a` inside a
    # branch, so closing it named `a` itself as an extra. A valid payload warned on every
    # single run — permanent false positives in the log `contract events` gates on.
    contract = Contract.model_validate({
        "system": "demo", "version": "1.0.0",
        "outputs": [{"name": "either", "schema": "aivx.oneof@1.0.0", "mode": "observe"}],
    })
    log = EventLog(tmp_path / "e.jsonl")
    rt = ContractRuntime(contract, Resolver([FIX / "schemas"]), event_log=log,
                         clock=lambda: "2026-07-16T00:00:00+00:00")

    @rt.output("either")
    def produce():
        return {"a": "hello"}

    produce()
    assert log.records()[-1]["result"] == "pass"
