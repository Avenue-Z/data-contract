# tests/test_value_constraints.py
from pathlib import Path

import pandas as pd
import pytest

from contract_core import ContractViolation, load_runtime

FIX = Path(__file__).parent / "fixtures"
SCHEMAS = FIX / "schemas"
CONTRACT = FIX / "consumer" / "contract_v2.yaml"


def _runtime():
    return load_runtime(CONTRACT, schema_paths=[SCHEMAS])


def _load(rt, frame):
    @rt.input("prompts")
    def load():
        return frame
    return load


def _good(**overrides):
    base = {"prompt": ["a", "b"], "sentiment": [0.5, -0.5],
            "position": [1, 2], "is_owned": [0, 1]}
    base.update(overrides)
    return pd.DataFrame(base)


def _violation(frame):
    with pytest.raises(ContractViolation) as ei:
        _load(_runtime(), frame)()
    return ei.value


def test_conforming_data_passes():
    # The true negative for the whole pipeline.
    assert _load(_runtime(), _good())() is not None


def test_out_of_range_value_hard_fails_with_count_and_samples():
    exc = _violation(_good(sentiment=[1.4, 0.5]))
    d = next(d for d in exc.diffs if d.field == "sentiment")
    assert d.problem == "value"
    assert d.constraint == "maximum=1.0"
    assert d.violating_rows == 1
    assert d.samples == ["1.4"]


def test_violating_rows_counts_every_offending_row():
    exc = _violation(_good(sentiment=[1.4, 2.7]))
    d = next(d for d in exc.diffs if d.field == "sentiment")
    assert d.violating_rows == 2


def test_samples_cap_at_three():
    frame = pd.DataFrame({"prompt": list("abcde"), "sentiment": [9.0] * 5,
                          "position": [1] * 5, "is_owned": [0] * 5})
    d = next(d for d in _violation(frame).diffs if d.field == "sentiment")
    assert d.violating_rows == 5
    assert len(d.samples) == 3


def test_enum_violation_is_reported():
    d = next(d for d in _violation(_good(is_owned=[0, 5])).diffs if d.field == "is_owned")
    assert d.problem == "value"
    assert d.constraint == "enum=[0, 1]"


def test_min_length_violation_is_reported():
    d = next(d for d in _violation(_good(prompt=["", "b"])).diffs if d.field == "prompt")
    assert d.constraint == "min_length=1"


def test_a_value_failure_is_not_reported_as_retyped():
    # Design §5.2: the whole classification story. Fails if the checks are built with
    # `name=` instead of `error=`.
    exc = _violation(_good(sentiment=[1.4, 0.5]))
    assert "retyped" not in [d.problem for d in exc.diffs]


def test_a_field_violating_two_constraints_reports_both():
    # Design §5.2.1: fails against the old last-wins de-dup, which kept one arbitrary diff.
    exc = _violation(_good(sentiment=[-9.0, 9.0]))
    got = sorted(d.constraint for d in exc.diffs if d.field == "sentiment")
    assert got == ["maximum=1.0", "minimum=-1.0"]


def test_wrong_dtype_reports_the_dtype_diff_and_drops_value_diffs():
    # Design §5.2.2: a value check on a str column raises, and pandera records the
    # TypeError as the failure case.
    exc = _violation(_good(sentiment=["not-a-number", "also-not"]))
    problems = {d.problem for d in exc.diffs if d.field == "sentiment"}
    assert problems == {"retyped"}


def test_no_typeerror_text_ever_reaches_samples():
    # The observable form of the rule above, and what fails if the drop rule runs after
    # aggregation instead of before it.
    exc = _violation(_good(sentiment=["not-a-number", "also-not"]))
    assert not any("TypeError" in s for d in exc.diffs for s in d.samples)


def test_nulls_do_not_trip_constraints():
    assert _load(_runtime(), _good(sentiment=[None, 0.5]))() is not None


def test_a_missing_column_still_reports_missing():
    frame = _good().drop(columns=["position"])
    d = next(d for d in _violation(frame).diffs if d.field == "position")
    assert d.problem == "missing"
    assert d.violating_rows is None
