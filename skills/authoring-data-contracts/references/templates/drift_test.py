"""TEMPLATE — the drift test that guards a `raw` boundary (R2).

ONE per `raw` boundary. `contract reconcile` finds it by AST-scanning your --tests paths for the
marker `@pytest.mark.raw_drift("<name>")` — the string MUST match the raw boundary's `name` in
contract.yaml. A declared raw boundary with no matching marker is a category-D reconcile failure.

reconcile reads the marker statically (it never runs your tests). But if you run these as real
pytest tests under --strict-markers, register the marker once in pyproject.toml (see ci-gate.yml).

What the test must actually prove: the adapter REJECTS an unknown/changed raw shape. An adapter that
silently coerces a changed vendor payload into the old schema defeats drift detection — that is the
one thing this test exists to catch. A hollow marked test satisfies reconcile but not the intent.
"""
import pytest

from my_pkg.boundaries import normalize   # the adapter under test


@pytest.mark.raw_drift("vendor_raw")       # MUST equal the raw boundary name in contract.yaml
def test_adapter_rejects_unknown_raw_shape():
    """The adapter fails loudly when the vendor payload loses/renames a field it depends on."""
    changed_payload = {"data": {"list": [{"dimensions": {}, "metrics": {}}]}}  # a shape the vendor drifted to
    with pytest.raises((KeyError, ValueError, TypeError)):
        normalize(changed_payload)
