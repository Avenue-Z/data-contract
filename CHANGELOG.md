# Changelog

All notable changes to `contract-core` are recorded here. This file is the canonical
release notes: `docs/consuming-repo-setup.md` tells consumers to read them before moving a
pin, and a release is an annotated git tag with no package-index page to carry notes.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

`contract-core` is **pre-1.0**. Under 0.x semantics a **minor** bump may carry breaking
changes to the public API or the authored format. Read the entry before moving a pin.

## [Unreleased]

## [0.1.0] — unreleased, pending tag

First installable release. Before this, `contract-core` existed only as an editable local
path, so no other repo could depend on it (risk R9).

### Added

- **A curated public API.** `contract_core` now exports exactly five names —
  `load_runtime`, `ContractRuntime`, `ContractViolation`, `FieldDiff`, `__version__` — and
  declares `__all__`. A frozen-surface test fails if that set changes, so a break must be
  deliberate and reviewed rather than silent.
- **`load_runtime(contract_path, *, schema_paths, enabled)`** — builds a runtime from a
  contract file, or returns a disabled no-op runtime.
- **`ContractRuntime.disabled(label)`** — a no-op runtime whose `raw`/`input`/`output` are
  the identity decorator. It performs no validation, no schema resolution and **no file
  I/O**, and emits exactly one `logging.warning` at construction naming the trigger.
- **`CONTRACT_DISABLED` kill switch.** On iff present and its value, stripped and
  lowercased, is not one of `""`, `"0"`, `"false"`, `"no"`. So `=1`/`=true`/`=yes`/`=on`
  disable; `=0`/`=false`/`=no`/empty/unset leave validation enabled. **"Off always wins"** —
  application code passing `enabled=True` cannot override the env var.
- **Consumer documentation** — `docs/consuming-repo-setup.md` covers the git-tag pin, the
  deploy-token prerequisite, the kill switch, and the absent-library fallback pattern.
- **A release procedure** in `CONTRIBUTING.md`.

### Changed

- **Version `0.0.1` → `0.1.0`**, and a test now fails if `__version__` skews from the
  version in `pyproject.toml`.

### Notes for consumers

- **Deep module paths are private.** `contract_core.runtime`, `.contract`, `.resolver`,
  `.schema`, `.events`, `.types`, `.families`, `.compile.*` and `.cli` may change without a
  major bump. Import only the five public names; run the CLI via the `contract` console
  script.
- **No auto-degrade.** A missing or malformed contract file raises; it never silently
  disables validation.
- `EventLog` is deliberately *not* exported and `load_runtime` takes no `event_log`
  parameter — the event-log sink abstraction is unbuilt, and exporting either would promise
  a hook that does not exist.
- `schema_paths` defaults to `("schemas",)`. The signature is stable, but if a central
  schema registry path is later prepended to that default, a different schema may resolve —
  that will be called out as a behavior change here.

[Unreleased]: https://github.com/Avenue-Z/data-contract/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Avenue-Z/data-contract/releases/tag/v0.1.0
