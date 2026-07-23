"""Shared fixtures. Prefer hand-rolled fakes over mock — the org's convention."""
from types import SimpleNamespace

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


# Shared reconcile fixture sources. `{SCHEMAS}`/`{CONTRACT}` are substituted by str .replace
# (NOT str.format — a fixture module may contain literal braces, e.g. a dict).
_RECONCILE_CONTRACT = (
    "system: fix-sys\n"
    "version: 1.0.0\n"
    "raw:\n"
    "  - {name: prompts_raw, schema: peec.prompts_export@1.0.0, mode: enforce}\n"
    "inputs:\n"
    "  - {name: prompts, schema: peec.prompts_export@1.0.0, mode: enforce}\n"
)
_RECONCILE_BOUNDARIES = (
    "from contract_core import load_runtime\n"
    "runtime = load_runtime(r'{CONTRACT}', schema_paths=[r'{SCHEMAS}'])\n"
    "\n"
    "@runtime.raw('prompts_raw')\n"
    "def fetch():\n"
    "    return None\n"
    "\n"
    "@runtime.input('prompts')\n"
    "def load():\n"
    "    return None\n"
)
# Same as _RECONCILE_BOUNDARIES but wires up ONLY input — raw is left declared-but-unregistered
# (the incident-#2 replay, category A).
_RECONCILE_INPUT_ONLY = (
    "from contract_core import load_runtime\n"
    "runtime = load_runtime(r'{CONTRACT}', schema_paths=[r'{SCHEMAS}'])\n"
    "\n"
    "@runtime.input('prompts')\n"
    "def load():\n"
    "    return None\n"
)


@pytest.fixture
def reconcile_sources():
    return SimpleNamespace(
        contract=_RECONCILE_CONTRACT,
        boundaries=_RECONCILE_BOUNDARIES,
        input_only=_RECONCILE_INPUT_ONLY,
    )


@pytest.fixture
def make_reconcile_pkg(tmp_path, monkeypatch):
    """Build an importable fixture package under tmp_path for force-import tests.

    `files` maps a path relative to the package root ("boundaries.py", "sub/__init__.py",
    ...) to source text; `{SCHEMAS}`/`{CONTRACT}` in it are substituted via .replace. A
    package `__init__.py` is created empty if absent. `contract` defaults to the shared
    raw+input contract. reconcile only *imports* the modules, so decorated function bodies
    never run and can be trivial.
    """
    from pathlib import Path
    SCHEMAS = Path(__file__).parent / "fixtures" / "schemas"

    def build(files, *, contract=_RECONCILE_CONTRACT, name="fixpkg"):
        cpath = tmp_path / f"{name}.contract.yaml"
        root = tmp_path / name
        for rel, src in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(src.replace("{SCHEMAS}", str(SCHEMAS)).replace("{CONTRACT}", str(cpath)))
        if not (root / "__init__.py").exists():
            (root / "__init__.py").write_text("")
        cpath.write_text(contract)
        monkeypatch.syspath_prepend(str(tmp_path))
        return SimpleNamespace(package=name, contract=str(cpath), root=root)

    return build
