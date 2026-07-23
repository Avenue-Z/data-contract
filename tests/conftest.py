"""Shared fixtures. Prefer hand-rolled fakes over mock — the org's convention."""
import pytest


@pytest.fixture(autouse=True)
def event_log_path(tmp_path, monkeypatch):
    """Point the default EventLog at tmp_path.

    `load_runtime` has no `event_log` parameter (a custom sink is not a supported capability
    yet — R9 design §3.2), so an enabled runtime built by the factory writes wherever
    CONTRACT_EVENT_LOG says, defaulting to ./contract-events.jsonl in the repo root.

    `autouse` because the failure mode of forgetting it is silent: a test that builds an
    enabled runtime without it writes contract-events.jsonl into the repo root, and that
    path is gitignored, so nothing complains. Tests that need the path still request it by
    name. No test depends on the default location — the EventLog tests pass an explicit one.
    """
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CONTRACT_EVENT_LOG", str(path))
    return path


@pytest.fixture(autouse=True)
def _reset_contract_registry():
    """Clear the boundary registry before each test (design §4 / §15 item 5).

    The registry is process-global; without this, one test's registrations leak into
    another's assertions (the order-dependence the pilot reported). Function-scoped and
    before the test body, which is where every test does its own decoration.
    """
    from contract_core.runtime import _reset_registry
    _reset_registry()
    yield
