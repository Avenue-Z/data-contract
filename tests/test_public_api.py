# tests/test_public_api.py
# Every import in this file is a TOP-LEVEL import on purpose. A deep-module import here
# (contract_core.runtime, .contract, .resolver, ...) defeats T3: the point is to prove the
# curated surface is sufficient for a real consumer. Do not add one.
from pathlib import Path

import pandas as pd
import pytest

import contract_core
from contract_core import ContractViolation, FieldDiff, load_runtime

# The frozen public surface (R9 design §3.2). Changing this set is a deliberate act:
# under 0.x a breaking change is allowed, but it must be conscious, reviewed, and carry a
# minor bump — this test is what makes "silent" impossible.
FROZEN_SURFACE = {
    "ContractFormatError",
    "ContractRuntime",
    "ContractViolation",
    "FieldDiff",
    "__version__",
    "load_runtime",
}


def test_public_surface_is_frozen():
    assert set(contract_core.__all__) == FROZEN_SURFACE


def test_all_has_no_duplicates():
    assert len(contract_core.__all__) == len(set(contract_core.__all__))


def test_every_promised_name_is_actually_importable():
    # __all__ is a promise, not proof: a name can be listed and not exported.
    for name in FROZEN_SURFACE:
        assert hasattr(contract_core, name), f"{name} is in __all__ but not on the package"


def test_no_module_alias_leaks_onto_the_public_surface():
    # "The import path is the contract": where load_runtime is DEFINED is an implementation
    # detail, and no `contract_core.api`-style import path is offered or supported.
    assert not hasattr(contract_core, "api")


FIX = Path(__file__).parent / "fixtures"
CONSUMER_CONTRACT = FIX / "consumer" / "contract.yaml"
SCHEMAS = FIX / "schemas"


def _good_df():
    return pd.DataFrame({
        "prompt": ["a"], "sentiment": [0.5],
        "position": pd.array([1], dtype="Int64"),
        "share_of_voice": [0.3],
    })


def test_public_api_is_sufficient_for_a_full_raw_input_output_flow(monkeypatch, event_log_path):
    """T3: a real consumer module, importing ONLY the top-level names."""
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    runtime = load_runtime(CONSUMER_CONTRACT, schema_paths=[SCHEMAS])

    @runtime.raw("prompts_raw")
    def fetch_raw():
        return _good_df()

    @runtime.input("prompts")
    def normalize():
        return fetch_raw()

    @runtime.output("report")
    def build_report():
        df = normalize()
        return {"slug": "acme", "score": float(df["sentiment"].iloc[0])}

    assert build_report() == {"slug": "acme", "score": 0.5}
    results = [line for line in event_log_path.read_text().splitlines() if line.strip()]
    assert len(results) == 3  # one event per crossing: raw, input, output


def test_field_diff_is_reachable_and_usable_off_a_caught_violation(
    monkeypatch, event_log_path
):
    """T5: catching a violation yields a usable list[FieldDiff], top-level imports only."""
    monkeypatch.delenv("CONTRACT_DISABLED", raising=False)
    runtime = load_runtime(CONSUMER_CONTRACT, schema_paths=[SCHEMAS])

    @runtime.input("prompts")
    def load():
        return _good_df().drop(columns=["position"])

    with pytest.raises(ContractViolation) as ei:
        load()

    diffs = ei.value.diffs
    assert diffs and all(isinstance(d, FieldDiff) for d in diffs)
    # These four attribute names are themselves part of the frozen surface: a consumer
    # reads them to build custom handling, so renaming one is a breaking change.
    diff = next(d for d in diffs if d.field == "position")
    assert diff.expected == "int"
    assert diff.observed == "absent"
    assert diff.problem == "missing"


def test_field_diff_carries_the_value_violation_fields():
    # A deliberate, reviewed surface change (R9 §3.2 / design §7): `FieldDiff` gained
    # three fields and `problem` gained a "value" variant in 0.2.0. Consumers matching
    # exhaustively on `problem` will see a value they have not seen before.
    names = set(FieldDiff.model_fields)
    assert names == {"field", "expected", "observed", "problem",
                     "constraint", "violating_rows", "samples"}


_DOCUMENTED_PRIVATE_MODULES = {
    "runtime", "errors", "contract", "resolver", "schema", "events", "types", "families",
    "vendor", "compile", "cli", "reconcile", "events_report", "scaffold",
}


def test_private_module_list_matches_the_modules_actually_present():
    """design §2.3: the docstring's private-module list is exhaustive by claim. Compare it
    against the filesystem so the next omission fails CI instead of aging into the docs."""
    from pathlib import Path

    src_dir = Path(contract_core.__file__).parent
    actual = {
        p.stem for p in src_dir.glob("*.py")
        if p.stem not in {"__init__", "__main__"}
    }
    actual |= {
        d.name for d in src_dir.iterdir()
        if d.is_dir() and (d / "__init__.py").is_file()
    }
    assert actual == _DOCUMENTED_PRIVATE_MODULES
