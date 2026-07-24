"""TEMPLATE — boundary wiring for an automation package.

Save as your package's boundary module (e.g. `my_pkg/boundaries.py`) and import it from the
package `__init__.py` so the decorators run at import time — `contract reconcile` imports the
package to discover registered boundaries.

Carries the three consumer-doc obligations this skill owns:
  - §1  pin contract-core by `.git@<tag>` (>= v0.5.0) — see pyproject / ci-gate.yml, not here
  - §3  the CONTRACT_DISABLED kill switch — honored automatically by load_runtime
  - §4  the absent-library no-op fallback — the try/except below (must NOT import from the library)

Boundary decorators MUST be at module top level (not inside a function/factory), or reconcile
cannot see them at import time and its registration set is incomplete.
"""
from __future__ import annotations

from pathlib import Path

# §4 — absent-library fallback. The library cannot catch its own missing import, so this lives in
# the consumer. The stand-in must not import anything from contract_core (it may be absent).
try:
    from contract_core import load_runtime

    _ROOT = Path(__file__).resolve().parent.parent
    # load_runtime honors CONTRACT_DISABLED (§3) itself — no per-call opt-in can defeat that switch.
    runtime = load_runtime(
        str(_ROOT / "contract.yaml"),
        schema_paths=[str(_ROOT / "schemas")],
    )
except ImportError:
    class _NoOpRuntime:
        """Stand-in when contract-core is not installed. Must NOT import from it."""
        def _passthrough(self, name):
            return lambda fn: fn
        raw = input = output = _passthrough

    runtime = _NoOpRuntime()


# ---- boundaries (top-level decorators only) ----

@runtime.raw("vendor_raw")            # ONLY for a mediated source (API/MCP/LLM); drop for file-ingest
def pull_raw(client, **params) -> dict:
    """The TRUE raw read — return the vendor payload unmodified, before any cleaning."""
    return client.get("/some/endpoint", params=params)


@runtime.input("normalized")
def normalize(raw: dict) -> "list[dict]":
    """Adapter: a dumb pass-through mapper to the normalized shape. Separately drift-tested."""
    ...


@runtime.output("report")
def build_report(rows, **ctx) -> dict:
    """Return the deliverable; it is validated BEFORE it is written to its sink."""
    ...
