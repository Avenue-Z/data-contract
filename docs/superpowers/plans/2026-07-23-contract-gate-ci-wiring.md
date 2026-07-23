# contract-gate CI Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a reusable `on: workflow_call` GitHub Actions workflow (plus a unit-tested helper script and consumer docs) that makes `contract lint` + `contract reconcile` a real, merge-blocking CI gate in repos that consume contract-core.

**Architecture:** A `workflow_call` workflow (`.github/workflows/contract-gate.yml`) checks out the caller's repo, self-checks-out *this* repo at the workflow's own tag to obtain a tested `scripts/expand-flags.sh`, installs the consumer project (which pulls the pyproject-pinned contract-core and the `contract` console script), then runs lint + reconcile — the gate is purely the exit code. The newline→repeated-flags expansion, the one false-red-prone piece of logic, lives in the tested script, not inline YAML.

**Tech Stack:** GitHub Actions (reusable workflow), Bash, Python 3.13, pytest (via subprocess, mirroring `tests/test_distribution.py`), Click CLI (`contract`).

**Spec:** [`docs/superpowers/specs/2026-07-23-contract-gate-ci-wiring-design.md`](../specs/2026-07-23-contract-gate-ci-wiring-design.md)

## Global Constraints

- **Branch flow:** already on `ci/contract-gate-ci-wiring`; the PR targets `dev`. Never push to `main`. Enforced by `guard-base-branch` / `scripts/check-base-branch.sh`, **not** code ownership (no CODEOWNERS file).
- **Do NOT touch** `.github/workflows/ci.yml` or `scripts/ci-aggregate-gate.sh`. The new workflow is `on: workflow_call` only — it adds no check context here and must not.
- **Pin actions by SHA**, the exact ones `ci.yml` already uses: `actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0` and `actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0`.
- **`permissions: contents: read`** at workflow level (least privilege).
- **Token hygiene:** never `set -x` in a step that sees the token; guard the token with `[ -n "${VAR:-}" ]` (the `:-` matters); scope the git `insteadOf` rewrite to exactly `https://github.com/Avenue-Z/data-contract`, never all of `github.com`.
- **No `${{ }}` interpolated directly into a `run:` body** — pass every input through `env:` first (injection hygiene; keeps actionlint clean).
- **Python floor 3.13** (`requires-python`). Default `python-version: "3.13"`.
- **Commit trailer** on every commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

- `scripts/expand-flags.sh` (**create**) — newline→NUL-delimited repeated-flags expander; skips blank lines. One responsibility: the risky expansion, isolated so it can be tested.
- `tests/test_expand_flags.py` (**create**) — pytest+subprocess unit test for the script; runs in the gating `test` job.
- `.github/workflows/contract-gate.yml` (**create**) — the reusable `workflow_call` gate.
- `docs/consuming-repo-setup.md` (**modify**) — new `## 7. Wiring the gate into CI` section, inserted before the closing italic note.
- `CHANGELOG.md` (**modify**) — new `## [Unreleased]` section above `## [0.4.0]`.

Task order: script+test first (Task 1) because the workflow (Task 2) references the script; docs+changelog last (Task 3) because they describe the shipped surface.

---

### Task 1: `expand-flags.sh` + its unit test

**Files:**
- Create: `scripts/expand-flags.sh`
- Test: `tests/test_expand_flags.py`

**Interfaces:**
- Consumes: nothing (leaf).
- Produces: `scripts/expand-flags.sh <flag-name>` — reads a newline-delimited value list on **stdin**, skips blank/whitespace-only lines, prints `<flag-name>\0<value>\0` for each remaining line (NUL-delimited). Exit 2 on wrong argument count. Task 2's workflow consumes this via `mapfile -d ''`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_expand_flags.py`:

```python
# tests/test_expand_flags.py
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "expand-flags.sh"


def _expand(flag: str, stdin: str) -> list[str]:
    """Run expand-flags.sh and return its NUL-delimited tokens as a list."""
    proc = subprocess.run(
        ["bash", str(SCRIPT), flag],
        input=stdin, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    tokens = proc.stdout.split("\0")
    # A trailing delimiter leaves an empty final element — drop it.
    if tokens and tokens[-1] == "":
        tokens.pop()
    return tokens


def test_multiple_lines_become_repeated_flags():
    assert _expand("--schemas", "schemas\nvendor/schemas\n") == [
        "--schemas", "schemas", "--schemas", "vendor/schemas",
    ]


def test_blank_and_trailing_lines_are_skipped():
    # Load-bearing: a stray blank / trailing line must NOT become --schemas ""
    assert _expand("--schemas", "schemas\n\n\nvendor\n") == [
        "--schemas", "schemas", "--schemas", "vendor",
    ]


def test_whitespace_only_line_is_skipped():
    assert _expand("--tests", "tests\n   \ndrift\n") == [
        "--tests", "tests", "--tests", "drift",
    ]


def test_empty_input_yields_no_flags():
    assert _expand("--schemas", "") == []
    assert _expand("--schemas", "\n\n") == []


def test_value_with_spaces_survives_as_one_token():
    # NUL delimiting is what makes this safe — a space in a path stays one argv element.
    assert _expand("--schemas", "dir with spaces/schemas\n") == [
        "--schemas", "dir with spaces/schemas",
    ]


def test_missing_flag_arg_is_a_usage_error():
    proc = subprocess.run(["bash", str(SCRIPT)], input="x\n",
                          capture_output=True, text=True)
    assert proc.returncode == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_expand_flags.py -q`
Expected: FAIL — the script does not exist yet (`_expand` asserts `returncode == 0`, but `bash` cannot open a missing file, so `returncode` is 127 and the assert fires; the usage test also fails).

- [ ] **Step 3: Write the script**

Create `scripts/expand-flags.sh`:

```bash
#!/usr/bin/env bash
# scripts/expand-flags.sh <flag-name>
#
# Turn a newline-delimited value list on stdin into the argv a REPEATABLE click option needs —
# `--schemas a --schemas b` — emitted NUL-delimited so the caller reads it with `mapfile -d ''` and
# every value survives intact (a path may contain spaces).
#
# The load-bearing behavior is SKIPPING BLANK LINES. A GitHub `with:` block written as
#     schemas: |
#       schemas
# arrives with a trailing newline; without the skip that becomes `--schemas ""`, which trips
# click.Path(exists=True) and fails the gate on a VALID contract — a false red, the worst thing a
# gate can do. This lives in a script (not inline workflow YAML) so tests exercise the SAME logic the
# workflow runs — the scripts/ci-aggregate-gate.sh / check-base-branch.sh pattern.
set -euo pipefail

[ "$#" -eq 1 ] || { echo "usage: expand-flags.sh <flag-name>" >&2; exit 2; }
flag="$1"

# `|| [ -n "$line" ]` so a final line with no trailing newline is still processed.
while IFS= read -r line || [ -n "${line}" ]; do
  # Skip blank / whitespace-only lines — the false-red guard.
  [ -n "${line//[[:space:]]/}" ] || continue
  printf '%s\0%s\0' "${flag}" "${line}"
done
```

- [ ] **Step 4: Make it executable**

Run: `chmod +x scripts/expand-flags.sh`
(Git tracks the exec bit; the workflow invokes the script directly.)

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_expand_flags.py -q`
Expected: PASS (6 passed).

- [ ] **Step 6: Confirm the full suite + lint are still green**

Run: `ruff check . && pytest -q`
Expected: PASS. (`ruff` checks the new `.py`; the `.sh` is not ruff-scanned. `mypy` is unaffected — no new typed source.)

- [ ] **Step 7: Commit**

```bash
git add scripts/expand-flags.sh tests/test_expand_flags.py
git commit -m "feat(ci): NUL-safe expand-flags.sh + unit test

The newline->repeated-flags expansion is the gate's most false-red-prone
logic (a trailing blank line becoming --schemas ''). Isolate it in a tested
script, per the ci-aggregate-gate.sh convention, so it is proven before a
consumer's PR is the test case.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The reusable `contract-gate.yml` workflow

**Files:**
- Create: `.github/workflows/contract-gate.yml`

**Interfaces:**
- Consumes: `scripts/expand-flags.sh --schemas` / `--tests` from Task 1 (invoked from the self-checked-out `./.contract-core/scripts/`).
- Produces: a callable workflow — `uses: Avenue-Z/data-contract/.github/workflows/contract-gate.yml@<tag>` with inputs `contract`, `package`, `schemas`, `tests`, `python-version`, `install-command` and secret `contract-core-token`. Task 3's docs snippet relies on exactly these names.

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/contract-gate.yml`:

```yaml
name: contract-gate

# Reusable gate: a consuming repo calls this to run `contract lint` + `contract reconcile` against
# ITS OWN contract and package, failing CI on any gating finding. It is `on: workflow_call` ONLY — it
# never runs on this repo's own PRs, adds no check context here, and cannot touch the required `ci`
# aggregate. Design: docs/superpowers/specs/2026-07-23-contract-gate-ci-wiring-design.md
on:
  workflow_call:
    inputs:
      contract:
        description: "Path to the contract file (shared by lint + reconcile)."
        required: true
        type: string
      package:
        description: "Importable package name for `reconcile --package`."
        required: true
        type: string
      schemas:
        description: "Schema dirs for `lint --schemas`, one per line (newline-delimited)."
        required: true
        type: string
      tests:
        description: "Test paths for `reconcile --tests`, one per line (newline-delimited)."
        required: true
        type: string
      python-version:
        description: "Python to run the gate under."
        required: false
        default: "3.13"
        type: string
      install-command:
        description: "Command that installs the consumer project + its pinned contract-core."
        required: false
        default: "pip install ."
        type: string
    secrets:
      contract-core-token:
        description: "Token with contents:read on Avenue-Z/data-contract, for pip's private clone."
        required: true

# Least privilege: this job reads code and reports a result; it never writes to the repo.
permissions:
  contents: read

jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      # 1. The CALLER's repo — the contract + package the gate runs against.
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0

      # 2. This repo's scripts. A workflow_call workflow checks out the CALLER, so
      #    scripts/expand-flags.sh is not otherwise on the runner. Check out data-contract at THIS
      #    workflow's own resolved tag so the *tested* expander runs — never a drift-prone inline copy.
      - name: Resolve this workflow's own ref
        id: ref
        run: |
          set -euo pipefail
          # GITHUB_WORKFLOW_REF looks like:
          #   owner/repo/.github/workflows/contract-gate.yml@refs/tags/v0.5.0
          echo "ref=${GITHUB_WORKFLOW_REF##*@}" >> "${GITHUB_OUTPUT}"
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          repository: Avenue-Z/data-contract
          ref: ${{ steps.ref.outputs.ref }}
          token: ${{ secrets.contract-core-token }}
          path: .contract-core
          persist-credentials: false

      # 3. Python.
      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6.3.0
        with:
          python-version: ${{ inputs.python-version }}

      # 4. Authenticate pip's clone of the private contract-core dependency — and NOTHING else.
      - name: Configure git auth for the private dependency
        env:
          CONTRACT_CORE_TOKEN: ${{ secrets.contract-core-token }}
        run: |
          set -euo pipefail
          [ -n "${CONTRACT_CORE_TOKEN:-}" ] || { echo "::error::contract-core-token is empty"; exit 1; }
          git config --global \
            url."https://x-access-token:${CONTRACT_CORE_TOKEN}@github.com/Avenue-Z/data-contract".insteadOf \
            "https://github.com/Avenue-Z/data-contract"

      # 5. Install the consumer project (brings in the pyproject-pinned contract-core and the
      #    `contract` console script). `install-command` is consumer-controlled shell.
      - name: Install the consumer project
        env:
          INSTALL_COMMAND: ${{ inputs.install-command }}
        run: |
          set -euo pipefail
          eval "${INSTALL_COMMAND}"

      # 6. Lint. Expand newline-delimited schema dirs into repeated --schemas flags via the TESTED
      #    script (Task 1), consumed NUL-safe with mapfile -d ''.
      - name: contract lint
        env:
          CONTRACT: ${{ inputs.contract }}
          SCHEMAS: ${{ inputs.schemas }}
        run: |
          set -euo pipefail
          mapfile -d '' schema_flags < <(.contract-core/scripts/expand-flags.sh --schemas <<< "${SCHEMAS}")
          contract lint --contract "${CONTRACT}" "${schema_flags[@]}"

      # 7. Reconcile. The gate IS the exit code — non-zero on any gating finding (P/A/B/C/D).
      - name: contract reconcile
        env:
          CONTRACT: ${{ inputs.contract }}
          PACKAGE: ${{ inputs.package }}
          TESTS: ${{ inputs.tests }}
        run: |
          set -euo pipefail
          mapfile -d '' test_flags < <(.contract-core/scripts/expand-flags.sh --tests <<< "${TESTS}")
          contract reconcile --contract "${CONTRACT}" --package "${PACKAGE}" "${test_flags[@]}"
```

- [ ] **Step 2: Install actionlint if absent**

Run: `command -v actionlint || brew install actionlint`
Expected: a path to `actionlint`, or a successful install.

- [ ] **Step 3: Validate the workflow with actionlint**

Run: `actionlint .github/workflows/contract-gate.yml`
Expected: no output, exit 0. (actionlint understands `shellcheck`-style shell; the `env:`-indirection of every input keeps it free of expression-injection warnings. If shellcheck is installed it also lints the `run:` blocks.)

- [ ] **Step 4: Confirm no new required context was introduced**

Run: `bash scripts/apply-rulesets.sh --dry-run`
Expected: the "required status checks" list names `ci` (and not `contract-gate`) — `apply-rulesets.sh` only ever adds `ci`/`template-tests`, so a new workflow file cannot silently become a required check. (If not authed to GitHub, the script exits early with a plan/remote warning — that is fine; the point is it does not add `contract-gate`.)

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/contract-gate.yml
git commit -m "feat(ci): reusable contract-gate workflow (lint + reconcile)

on: workflow_call only, so it adds no check context to this repo. Installs the
caller's project, self-checks-out data-contract at this workflow's own tag for
the tested expand-flags.sh, then runs lint + reconcile — the gate is the exit
code. contents: read, SHA-pinned actions, scoped insteadOf, empty-token guard.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Consumer docs (§7) + CHANGELOG

**Files:**
- Modify: `docs/consuming-repo-setup.md` (insert `## 7.` before the closing `---` italic note near the end)
- Modify: `CHANGELOG.md` (insert `## [Unreleased]` above `## [0.4.0]`)

**Interfaces:**
- Consumes: the workflow input/secret names from Task 2 (`contract`, `package`, `schemas`, `tests`, `contract-core-token`).
- Produces: consumer-facing documentation. Nothing depends on it.

- [ ] **Step 1: Insert the §7 docs section**

In `docs/consuming-repo-setup.md`, find the end of §6 and the closing block:

```markdown
This is *your* pytest configuration, not something the library ships — `contract-core`'s own suite
side-steps it by naming its reconcile fixtures `drift_*.py` (never collected), which a consuming
repo running real drift tests cannot do.

---

*When the §5.5 authoring skill lands in Phase 1, it must carry §1 (the pin + deploy token), §3 (the
```

Insert the following **between** the end of §6 (`...cannot do.`) and the `---` line:

````markdown

## 7. Wiring the gate into CI

`contract lint` + `contract reconcile` only protect you if CI runs them on every PR. This repo ships
a reusable workflow that does exactly that.

**Prerequisite, not a footnote:** `data-contract` is private, so a reusable workflow it hosts is
invisible to your repo until an admin enables, once, **Settings → Actions → General → Access →
"Accessible from repositories in the Avenue-Z organization"** on `data-contract`. A `workflow was not
found` error means *that setting is off* — it is **not** the `contract-core-token`, which only clones
the dependency. If the setting cannot be enabled, use the inline alternative below; it calls nothing
cross-repo.

**Pin the same tag you pin contract-core to.** The workflow ships the CLI flag names at its tag,
while your `pyproject.toml` (§1) pins the CLI it drives, and a 0.x minor may change that surface (read
[`CHANGELOG.md`](../CHANGELOG.md)). So the workflow `@tag` and your contract-core pin **must be the
same tag** — a mismatch is silent CLI breakage, not a warning — and at or above the release that
introduced the gate.

### Call the reusable workflow

```yaml
# .github/workflows/contract.yml in YOUR repo
name: contract
on:
  pull_request:
  push:
    branches: [main]   # your protected branches

jobs:
  gate:
    # Same tag as your contract-core pin (see above).
    uses: Avenue-Z/data-contract/.github/workflows/contract-gate.yml@v0.4.0
    with:
      contract: contract.yaml
      package: my_pkg              # importable — reconcile imports it to find registered boundaries
      schemas: |                   # one dir per line
        schemas
      tests: |                     # one path per line
        tests
    secrets:
      # A token/deploy key with contents:read on Avenue-Z/data-contract (§1).
      contract-core-token: ${{ secrets.CONTRACT_CORE_READ_TOKEN }}
```

`schemas` and `tests` are **newline-delimited** — one path per line under a `|` block. A blank or
trailing line is ignored, so a stray newline will not fail the gate.

### Exit-code semantics

The gate **is** the exit code; nothing parses output. `lint` exits non-zero on a malformed contract,
malformed schema, or unresolved schema ref. `reconcile` exits non-zero on any gating finding
(categories P/A/B/C/D — see the reconcile design) and on a malformed contract. Any non-zero fails the
check. The `raw_drift` marker is read by AST and needs no registration on reconcile's side — but if
you run your drift tests as collected pytest tests under `--strict-markers`, register the marker as
§6 shows, or pytest rejects it at collection.

### Inline alternative (no cross-repo call)

If you would rather not depend on the reusable workflow — or cannot enable the Actions-access setting
above — run the two commands directly. Pin the marketplace actions to your repo's policy.

```yaml
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Install and run the gate
        env:
          CONTRACT_CORE_TOKEN: ${{ secrets.CONTRACT_CORE_READ_TOKEN }}
        run: |
          set -euo pipefail
          [ -n "${CONTRACT_CORE_TOKEN:-}" ] || { echo "::error::CONTRACT_CORE_READ_TOKEN is empty"; exit 1; }
          git config --global \
            url."https://x-access-token:${CONTRACT_CORE_TOKEN}@github.com/Avenue-Z/data-contract".insteadOf \
            "https://github.com/Avenue-Z/data-contract"
          pip install .
          contract lint --contract contract.yaml --schemas schemas
          contract reconcile --contract contract.yaml --package my_pkg --tests tests
```
````

- [ ] **Step 2: Verify the insertion is well-formed**

Run: `grep -n "^## " docs/consuming-repo-setup.md`
Expected: sections `## 1.` … `## 6.` … `## 7. Wiring the gate into CI`, with §7 appearing **before** the closing `---`/italic note. Confirm the closing italic note is still the last content in the file.

- [ ] **Step 3: Add the CHANGELOG `[Unreleased]` entry**

In `CHANGELOG.md`, immediately above the line `## [0.4.0] — 2026-07-23`, insert:

```markdown
## [Unreleased]

### Added

- **`contract-gate` reusable CI workflow** (`.github/workflows/contract-gate.yml`, `on:
  workflow_call`) — a consuming repo calls it to install its project, run `contract lint` +
  `contract reconcile`, and fail CI on any gating finding, turning the reconcile gate into a real
  merge block. Pin it at the **same tag** as your contract-core dependency. See
  [`docs/consuming-repo-setup.md`](docs/consuming-repo-setup.md) §7. One-time enablement required:
  private-repo reusable-workflow "Actions access" sharing on this repo.

```

- [ ] **Step 4: Verify CHANGELOG placement**

Run: `grep -n "^## \[" CHANGELOG.md | head -3`
Expected: `## [Unreleased]` appears above `## [0.4.0] — 2026-07-23`.

- [ ] **Step 5: Commit**

```bash
git add docs/consuming-repo-setup.md CHANGELOG.md
git commit -m "docs(consuming): §7 wiring the gate into CI + CHANGELOG note

Copy-pasteable uses: snippet, inline alternative, exit-code semantics, the
Actions-access prerequisite, and the hard same-tag requirement.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Operational hand-off (not a code task — spec §10)

This PR ships code and docs; it does **not** make the gate callable by itself. Before or at the
release that first carries `contract-gate.yml`, an **Avenue-Z admin must enable Settings → Actions →
General → Access → "Accessible from repositories in the organization"** on `data-contract`. Until
then, a consumer's `uses:` call fails with `workflow was not found` before any step runs (spec §9
criterion #3, §10). Surface this in the PR description as an explicit release-checklist item.

---

## Self-Review

**Spec coverage:**
- §2 in-scope (workflow, docs, changelog, tested script) → Tasks 1–3. ✓
- §4.1 interface (all inputs/secret, `install-command`, no version input) → Task 2 workflow. ✓
- §4.2 permissions + SHA pins → Task 2 + Global Constraints. ✓
- §4.3 step order (caller checkout, self-checkout, setup-python, git auth w/ `:-` guard + scoped `insteadOf`, install, lint, reconcile) → Task 2. ✓
- §4.3.1 tested `expand-flags.sh` + self-checkout via `github.workflow_ref` → Task 1 + Task 2 step 2. ✓
- §4.4 / §10 Actions-access prerequisite → docs §7 (Task 3) + Operational hand-off. ✓
- §5 no `ci.yml`/aggregate change → Global Constraints + Task 2 step 4 verification. ✓
- §6 docs (uses: snippet, inline alternative, exit codes, raw_drift cross-ref, newline-delimited, same-tag hard rule, fork assumption via empty-token guard) → Task 3 step 1. ✓
- §7 CHANGELOG `[Unreleased]` → Task 3 step 3. ✓
- §8 actionlint + expand-flags unit test in gating `test` job → Task 2 step 3 + Task 1. ✓
- §9 criteria 1–5 → covered across Tasks 1–3 and the hand-off. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows complete content. ✓

**Type/name consistency:** `expand-flags.sh <flag-name>` reads stdin, emits NUL pairs, exit 2 on misuse — identical in Task 1 (definition/test) and Task 2 (`mapfile -d '' … < <(.contract-core/scripts/expand-flags.sh --schemas <<< "${SCHEMAS}")`). Workflow input names (`contract`/`package`/`schemas`/`tests`/`python-version`/`install-command`) and secret (`contract-core-token`) match between Task 2 and the Task 3 docs snippet. ✓
