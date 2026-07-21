# tests/test_public_api.py
# Every import in this file is a TOP-LEVEL import on purpose. A deep-module import here
# (contract_core.runtime, .contract, .resolver, ...) defeats T3: the point is to prove the
# curated surface is sufficient for a real consumer. Do not add one.
import contract_core

# The frozen public surface (R9 design §3.2). Changing this set is a deliberate act:
# under 0.x a breaking change is allowed, but it must be conscious, reviewed, and carry a
# minor bump — this test is what makes "silent" impossible.
FROZEN_SURFACE = {
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
