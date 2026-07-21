# src/contract_core/__init__.py
"""contract-core — the public API.

Everything exported here is a semver obligation (R9 design §3.2). Everything else —
`contract`, `schema`, `events`, `resolver`, `types`, `families`, `compile.*`, `cli` — is
**private**: import paths into those modules are not supported and may change without a
major bump. The CLI is invoked through the `contract` console script, not by importing
`contract_core.cli`.
"""
from contract_core.errors import ContractViolation, FieldDiff
from contract_core.runtime import ContractRuntime, load_runtime

__version__ = "0.1.0"

__all__ = [
    "ContractRuntime",
    "ContractViolation",
    "FieldDiff",
    "__version__",
    "load_runtime",
]
