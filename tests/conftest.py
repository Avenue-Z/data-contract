"""Shared fixtures. Prefer hand-rolled fakes over mock — the org's convention."""
import pytest


@pytest.fixture
def event_log_path(tmp_path, monkeypatch):
    """Point the default EventLog at tmp_path.

    `load_runtime` has no `event_log` parameter (a custom sink is not a supported capability
    yet — R9 design §3.2), so an enabled runtime built by the factory writes wherever
    CONTRACT_EVENT_LOG says, defaulting to ./contract-events.jsonl in the repo root.
    """
    path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CONTRACT_EVENT_LOG", str(path))
    return path
