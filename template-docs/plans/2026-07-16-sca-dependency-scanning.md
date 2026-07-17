# SCA (dependency-vulnerability scanning) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tiered, fail-safe SCA (Software Composition Analysis) to the template — an `sca` CI check that blocks `client-facing` repos on High/Critical dependency vulnerabilities *that have a fix*, warns everywhere else, and can never make a repo unmergeable over an unpatchable finding.

**Architecture:** A single **core** workflow `.github/workflows/sca.yml` (ships into every generated repo, exactly like `secret-scan.yml`) resolves the dependency tree with `osv-scanner`, then hands the JSON report to a committed, standalone gate script `scripts/sca-gate.sh`. The gate reads the tier from a committed, CODEOWNERS-guarded policy file `.github/sca-policy.json` (default `client-facing`) and applies the threshold. Because the gate is a plain script, its invariant is unit-tested against recorded OSV-shaped JSON fixtures rather than asserted in prose. Enforcement is a **baked-in required status check** in `repo-ruleset.json` (like `secret-scan`), not a dynamic one. Auto-remediation (Dependabot security updates) is a repo *setting*, so it lives as a gated step in the adoption playbook.

**Tech Stack:** GitHub Actions (YAML), Bash, `osv-scanner` v2.4.0 (verified binary download, checksum-pinned — mirrors the `gitleaks` install in `secret-scan.yml`), `jq` (preinstalled on `ubuntu-latest`, already a repo dependency), the `template-tests/` bash suite (`lib.sh`).

## Global Constraints

Copied verbatim from `docs/superpowers/specs/2026-07-16-hardening-additions-sca-and-supply-chain-design.md` (Item 1). Every task's requirements implicitly include these:

- **The invariant, across every tier:** *never block on a finding with no available fix.* Severity floor AND fix-availability must both be true to block.
- **Two tiers only:** `client-facing` (default) blocks on Critical/High **that have a fix**, warns on everything else; `internal` blocks on nothing, warns on everything.
- **Fail-safe default.** The template ships `client-facing`. Downgrading to `internal` is the explicit act (safe-by-neglect, never vulnerable-by-neglect).
- **Committed, code-owned policy value.** The tier lives in a version-controlled file that `.github/` CODEOWNERS guards — mirroring `vercel.json`'s `deploymentEnabled: false`.
- **Tooling today (private + Free):** `osv-scanner` in a workflow, reading the resolved tree, applying the tier's severity/fix threshold. Language-agnostic.
- **Stated boundary (SECURITY.md):** *The tier is only as current as the last person who set it. Exposure changes over a repo's life; the template makes the setting visible and reviewed, it cannot keep it correct as the product changes.*
- **Repo idioms that are non-negotiable here** (from the existing workflows/scripts): every workflow declares `permissions: contents: read`; every action is pinned to an explicit major tag, none float on `@main/@master/@latest` (enforced by `test_action_pins.sh`); security-critical binaries are downloaded with `--fail` + `sha256sum` checksum verification (not via a third-party action); the required-check job key must be **literally `sca`** and **non-matrix** (a required context that never reports hangs every PR pending forever; enforced by `test_rulesets.sh`); shell is `set -euo pipefail` and shellcheck-clean; tests use `template-tests/lib.sh` assertions and its loud `skip` (a skipped check is not a pass).

## Testing target (design §Testing, Item 1)

A `template-tests/` case must assert: **(a)** the shipped default tier is `client-facing` (fail-safe); **(b)** the policy file is present and referenced by the SCA workflow; **(c)** the never-block-without-a-fix invariant is encoded in the workflow's threshold logic, not just prose. All three land in `template-tests/test_sca.sh`.

---

## File Structure

| File | New/Mod | Responsibility | Ships into generated repos? |
|---|---|---|---|
| `.github/sca-policy.json` | Create | The one committed, CODEOWNERS-guarded policy value: `{"tier":"client-facing"}`. | **Yes** (under `.github/`, not stripped) |
| `scripts/sca-gate.sh` | Create | Pure gate logic: read tier + osv JSON, apply severity/fix threshold + invariant, exit 0/1. Unit-testable. | **Yes** (`scripts/` kept by init-repo) |
| `.github/workflows/sca.yml` | Create | Core workflow: install osv-scanner (verified), scan tree → JSON, call the gate. Job key `sca`. | **Yes** (core workflow, like `secret-scan.yml`) |
| `.github/rulesets/repo-ruleset.json` | Modify | Bake `sca` into `required_status_checks` (alongside `guard-base-branch`, `secret-scan`). | **Yes** (ruleset is shared) |
| `docs/ADOPTION.md` | Modify | Gated step: enable Dependabot alerts + security updates (a repo setting). | No (removed at adoption — correct home) |
| `scripts/init-repo.sh` | Modify | One line in the "Done. Next:" epilogue pointing at the Dependabot-enable step (ADOPTION.md is gone by then). | n/a |
| `SECURITY.md` | Modify | The stated tier-currency boundary + the no-fix-never-blocks rationale. | **Yes** |
| `template-tests/test_sca.sh` | Create | (a)(b)(c) + behavioral invariant tests driving `sca-gate.sh` with fixtures. | No (`template-tests/` stripped) |
| `template-tests/test_rulesets.sh` | Modify | Add `sca` to the expected required-context set + reachability. | No |
| `template-tests/test_init_repo.sh` | Modify | Assert the three SCA files ship; assert `test_sca.sh` is stripped. | No |

**No `init-repo.sh` strip/copy change is needed for the SCA files themselves:** generated repos ship everything under `.github/` and `scripts/` except the explicit strips (`templates/`, `template-tests/`, `template-tests.yml`, dated specs/plans, `ADOPTION.md`, README swap). The three new SCA files fall outside every strip and ship automatically. Verified against `scripts/init-repo.sh:330-375`.

---

### Task 1: Policy file + gate script (the invariant, TDD with fixtures)

This is the heart of the feature: the tier/severity/fix threshold and the invariant. Build it as a standalone script so the invariant is proven by exit-code tests, not prose.

**Files:**
- Create: `.github/sca-policy.json`
- Create: `scripts/sca-gate.sh`
- Create: `template-tests/test_sca.sh` (gate/invariant portion; workflow + docs assertions are added in Tasks 2 and 5)

**Interfaces:**
- Produces: `scripts/sca-gate.sh <osv-json-path> <policy-json-path>` → exit `0` (nothing blocks / warn-only) or `1` (client-facing gate: a High/Critical finding with a fix exists). Exit `2` only on a missing hard dependency (`jq`). Reads the tier via `jq -r '.tier'` from the policy file; a missing/invalid tier defaults to `client-facing` (strict).
- Produces: `.github/sca-policy.json` with a top-level string field `tier` ∈ {`client-facing`, `internal`}.

- [ ] **Step 1: Write the failing test (gate behavior + invariant + shipped default)**

Create `template-tests/test_sca.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=template-tests/lib.sh disable=SC1091
source template-tests/lib.sh

# ---------------------------------------------------------------------------------------
# THE INVARIANT IS THE WHOLE POINT: never block on a finding with no available fix, in any
# tier. These tests drive scripts/sca-gate.sh with recorded osv-scanner-shaped JSON and assert
# the EXIT CODE — so the invariant lives in a test, not in prose (design §Testing (c)).

GATE=scripts/sca-gate.sh
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# --- policy fixtures -------------------------------------------------------------------
printf '{"tier":"client-facing"}\n' > "$TMP/client.json"
printf '{"tier":"internal"}\n'      > "$TMP/internal.json"
printf '{"nope":true}\n'            > "$TMP/malformed.json"   # no tier -> must default to strict

# --- osv report fixtures (minimal, matching results[].packages[].vulnerabilities[]) ----
cat > "$TMP/high_fixed.json" <<'JSON'
{ "results": [ { "packages": [ {
  "package": { "name": "acme", "version": "1.0.0", "ecosystem": "npm" },
  "vulnerabilities": [ {
    "id": "GHSA-high-fixed",
    "database_specific": { "severity": "HIGH" },
    "affected": [ { "ranges": [ { "type": "SEMVER", "events": [ {"introduced":"0"}, {"fixed":"1.0.1"} ] } ] } ]
  } ] } ] } ] }
JSON

cat > "$TMP/critical_nofix.json" <<'JSON'
{ "results": [ { "packages": [ {
  "package": { "name": "acme", "version": "1.0.0", "ecosystem": "npm" },
  "vulnerabilities": [ {
    "id": "GHSA-crit-nofix",
    "database_specific": { "severity": "CRITICAL" },
    "affected": [ { "ranges": [ { "type": "SEMVER", "events": [ {"introduced":"0"} ] } ] } ]
  } ] } ] } ] }
JSON

cat > "$TMP/moderate_fixed.json" <<'JSON'
{ "results": [ { "packages": [ {
  "package": { "name": "acme", "version": "1.0.0", "ecosystem": "npm" },
  "vulnerabilities": [ {
    "id": "GHSA-mod-fixed",
    "database_specific": { "severity": "MODERATE" },
    "affected": [ { "ranges": [ { "type": "SEMVER", "events": [ {"introduced":"0"}, {"fixed":"1.0.1"} ] } ] } ]
  } ] } ] } ] }
JSON

printf '{"results":[]}\n' > "$TMP/empty.json"

# run the gate, capture its exit code WITHOUT tripping set -e (the lib pattern)
gate_rc() { local rc=0; "$GATE" "$1" "$2" >/dev/null 2>&1 || rc=$?; echo "$rc"; }

echo "sca-gate: block only High+/fixable on client-facing; never block a no-fix finding"
assert_eq 1 "$(gate_rc "$TMP/high_fixed.json"     "$TMP/client.json")"    "client-facing blocks a HIGH finding that HAS a fix"
assert_eq 0 "$(gate_rc "$TMP/high_fixed.json"     "$TMP/internal.json")"  "internal only warns on the same HIGH+fix finding"
assert_eq 0 "$(gate_rc "$TMP/critical_nofix.json" "$TMP/client.json")"    "client-facing does NOT block a CRITICAL finding with NO fix (the invariant)"
assert_eq 0 "$(gate_rc "$TMP/moderate_fixed.json" "$TMP/client.json")"    "client-facing does NOT block a MODERATE finding (below the High floor)"
assert_eq 0 "$(gate_rc "$TMP/empty.json"          "$TMP/client.json")"    "an empty report passes"
assert_eq 1 "$(gate_rc "$TMP/high_fixed.json"     "$TMP/malformed.json")" "a policy with no valid tier defaults to client-facing (strict) and still blocks"
assert_eq 0 "$(gate_rc "$TMP/does-not-exist.json" "$TMP/client.json")"    "a missing/empty osv report passes (osv-scanner found no packages)"

# --- design §Testing (a): the shipped default tier is the fail-safe 'client-facing' ----
echo "sca policy: the shipped default tier is the fail-safe 'client-facing'"
assert_file "the SCA policy file exists" .github/sca-policy.json
assert_eq "client-facing" "$(jq -r '.tier' .github/sca-policy.json)" "shipped .github/sca-policy.json tier == client-facing"

finish
```

- [ ] **Step 2: Run the test to verify it fails (gate script does not exist yet)**

Run: `bash template-tests/test_sca.sh`
Expected: FAIL — the `gate_rc` calls return non-zero from "No such file" so several `assert_eq` lines fail, and `assert_file .github/sca-policy.json` fails. Ends with `N FAILURE(S)`.

- [ ] **Step 3: Create the policy file**

Create `.github/sca-policy.json`:

```json
{
  "tier": "client-facing",
  "_comment": "SCA gate tier. 'client-facing' (default) blocks CI on High/Critical dependency vulnerabilities THAT HAVE A FIX; 'internal' warns only. NEITHER tier ever blocks a finding with no available fix. This file is CODEOWNERS-guarded (mirrors vercel.json's deploymentEnabled) — loosening to 'internal' takes a reviewed PR. See SECURITY.md."
}
```

- [ ] **Step 4: Write the gate script**

Create `scripts/sca-gate.sh`:

```bash
#!/usr/bin/env bash
# scripts/sca-gate.sh <osv-json> <policy-json>
#
# Applies the SCA policy tier to an osv-scanner JSON report and sets the check verdict.
#
# THE INVARIANT (holds in EVERY tier): never block on a finding with no available fix. A finding
# blocks ONLY IF its severity is High/Critical AND a fixed version exists. This is what stops a new
# CVE against an already-pinned dep from making every open PR unmergeable over something nobody can
# fix — the exact pathology the design rejects.
#
#   client-facing -> exit 1 if any blocking finding exists; else 0 (warn)
#   internal      -> always exit 0 (warn only)
set -euo pipefail

OSV_JSON="${1:?usage: sca-gate.sh <osv-json> <policy-json>}"
POLICY="${2:?usage: sca-gate.sh <osv-json> <policy-json>}"

command -v jq >/dev/null 2>&1 || { echo "::error::jq is required but not installed" >&2; exit 2; }

# Fail-safe: an unreadable or tier-less policy is treated as the STRICT default, never as a bypass.
tier="$(jq -r '.tier // empty' "${POLICY}" 2>/dev/null || true)"
case "${tier}" in
  client-facing|internal) ;;
  *) echo "::warning::sca-policy tier missing/invalid ('${tier:-}') — defaulting to client-facing (strict)"; tier="client-facing" ;;
esac

# osv-scanner writes nothing (and exits 128) when it finds no packages/lockfiles. An absent or empty
# report is "nothing to scan", a clean pass — never a crash.
if [ ! -s "${OSV_JSON}" ]; then
  echo "sca: no osv-scanner report (no packages/lockfiles found) — nothing to scan"
  exit 0
fi

# All findings, for the informational warn line (every severity, regardless of threshold).
all_ids="$(jq -r '[ .results[]?.packages[]?.vulnerabilities[]? | .id ] | unique | .[]' "${OSV_JSON}")"
[ -n "${all_ids}" ] && { echo "sca: findings (all severities):"; echo "${all_ids}" | sed 's/^/  - /'; }

# A "blocking" finding = severity High/Critical AND a fix is available.
#   Severity: database_specific.severity (populated for GitHub-Advisory-sourced records — the
#     dominant case for npm/PyPI/etc). A record carrying ONLY a CVSS vector and no
#     database_specific.severity is treated as severity-unknown -> NOT blocking. That is the honest
#     conservative reading: block only on findings we can positively classify as High+, never on
#     noise. (Boundary is stated in SECURITY.md; Task 2 verifies this field is present in real output.)
#   Fix available: any affected range carrying a `fixed` event.
blocking="$(jq -r '
  [ .results[]?.packages[]?.vulnerabilities[]?
    | select( (.database_specific.severity // "" | ascii_upcase) as $s | $s == "HIGH" or $s == "CRITICAL" )
    | select( any(.affected[]?.ranges[]?.events[]?; has("fixed")) )
    | .id ]
  | unique | .[]' "${OSV_JSON}")"

if [ -z "${blocking}" ]; then
  echo "sca: no High/Critical finding with an available fix — nothing blocks (tier: ${tier})"
  exit 0
fi

echo "::group::sca: High/Critical findings WITH an available fix"
echo "${blocking}" | sed 's/^/  - /'
echo "::endgroup::"

if [ "${tier}" = "client-facing" ]; then
  echo "::error::sca gate (client-facing): the finding(s) above are High/Critical AND have a fix. Bump the dependency (Dependabot may already have a PR open) to clear this check."
  exit 1
fi

echo "::warning::sca gate (internal): High/Critical findings with fixes exist, but this repo's tier is 'internal' — warning only, not blocking."
exit 0
```

- [ ] **Step 5: Make the gate executable**

Run: `chmod +x scripts/sca-gate.sh`

- [ ] **Step 6: Run the test to verify it passes**

Run: `bash template-tests/test_sca.sh`
Expected: PASS — every `assert_eq`/`assert_file` line prints `ok`, ending with `ALL PASS`.

- [ ] **Step 7: shellcheck the gate**

Run: `shellcheck scripts/sca-gate.sh`
Expected: no findings (only any pre-existing, unrelated repo warnings if run repo-wide).

- [ ] **Step 8: Commit**

```bash
git add .github/sca-policy.json scripts/sca-gate.sh template-tests/test_sca.sh
git commit -m "feat: SCA policy + gate script with the never-block-without-a-fix invariant"
```

---

### Task 2: The SCA workflow (`sca.yml`)

Wire the gate into CI: install `osv-scanner` with the same verified-download rigor `secret-scan.yml` uses for `gitleaks`, scan the tree to JSON, hand it to the gate.

**Files:**
- Create: `.github/workflows/sca.yml`
- Modify: `template-tests/test_sca.sh` (append workflow-wiring assertions — design §Testing (b))

**Interfaces:**
- Consumes: `scripts/sca-gate.sh` and `.github/sca-policy.json` from Task 1.
- Produces: a required-check context named `sca` (job key `sca`, non-matrix) that Task 3's ruleset requires.

- [ ] **Step 1: Append the failing workflow-wiring assertions to `template-tests/test_sca.sh`**

Insert immediately **before** the final `finish` line of `template-tests/test_sca.sh`:

```bash
# --- design §Testing (b): the policy is present AND referenced by the SCA workflow ------
echo "sca workflow: it reads the policy and runs the gate under a job named 'sca'"
WF=.github/workflows/sca.yml
assert_file "the SCA workflow exists" "$WF"
wf="$(cat "$WF")"
assert_match "sca.yml runs scripts/sca-gate.sh"           'scripts/sca-gate\.sh'      "$wf"
assert_match "sca.yml references .github/sca-policy.json"  '\.github/sca-policy\.json' "$wf"
assert_match "sca.yml declares a job keyed 'sca' (the required context must reach a real job)" '^[[:space:]]*sca:' "$wf"
assert_match "sca.yml is read-only (permissions: contents: read)" 'contents:[[:space:]]*read' "$wf"
```

- [ ] **Step 2: Run the test to verify the new assertions fail**

Run: `bash template-tests/test_sca.sh`
Expected: FAIL — `assert_file "the SCA workflow exists"` and the four `assert_match` lines fail (`.github/workflows/sca.yml` does not exist). Task 1's assertions still pass.

- [ ] **Step 3: Create the workflow**

Create `.github/workflows/sca.yml`:

```yaml
name: sca

on:
  pull_request:
  push:
    branches: [dev, staging, main]

# Read-only: this job resolves the dependency tree and reports a check. It never writes to the repo,
# so it must not inherit whatever the repo/org default GITHUB_TOKEN scope happens to be. Same
# reasoning as secret-scan.yml.
permissions:
  contents: read

# The job key MUST be literally `sca`. .github/rulesets/repo-ruleset.json requires the status-check
# context "sca" (BAKED IN, like secret-scan, because this workflow ships into every generated repo).
# A required check that never reports does not fail a PR — it hangs it PENDING FOREVER and nothing
# can be merged. template-tests/test_rulesets.sh asserts this job exists and is non-matrix.
jobs:
  sca:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      - name: install osv-scanner
        run: |
          set -euo pipefail
          # Pinned. Dependabot cannot bump a binary downloaded inside a run, so this is a MANUAL
          # bump — the same tradeoff secret-scan.yml makes for gitleaks.
          OSV_VERSION="2.4.0"
          ASSET="osv-scanner_linux_amd64"
          BASE_URL="https://github.com/google/osv-scanner/releases/download/v${OSV_VERSION}"
          # --fail is load-bearing: without it curl exits 0 on a 404 and writes the HTML error page
          # under the asset name, surfacing later as a baffling exec or checksum error.
          curl --fail -sSLo "${ASSET}" "${BASE_URL}/${ASSET}"
          curl --fail -sSLo osv-scanner_SHA256SUMS "${BASE_URL}/osv-scanner_SHA256SUMS"
          # The SHA256SUMS file lists every asset; --ignore-missing verifies only the one on disk
          # (and ERRORS if it is absent, so this cannot silently verify nothing).
          sha256sum --ignore-missing -c osv-scanner_SHA256SUMS
          chmod +x "${ASSET}"
          sudo mv "${ASSET}" /usr/local/bin/osv-scanner
          osv-scanner --version

      - name: scan the dependency tree and apply the policy
        run: |
          set -euo pipefail
          # osv-scanner exits 1 when it finds ANY vulnerability and 128 when it finds no packages.
          # Neither is this gate's verdict — the tier threshold is applied by sca-gate.sh — so
          # capture the report and never let the raw scan exit fail the job here.
          osv-scanner scan -r --format json --output-file osv.json ./ || true
          scripts/sca-gate.sh osv.json .github/sca-policy.json
```

- [ ] **Step 4: EMPIRICALLY confirm the osv-scanner v2 invocation and JSON schema**

The gate's severity path (`.database_specific.severity`) and the scan flags (`scan -r --format json --output-file`) were designed from docs, not from a live run. Confirm both against the real tool before trusting them:

```bash
# in a throwaway dir
mkdir /tmp/sca-probe && cd /tmp/sca-probe
# a lockfile with a known-vulnerable, since-fixed package (any ecosystem osv-scanner supports)
printf '{"name":"probe","lockfileVersion":3,"packages":{"node_modules/lodash":{"version":"4.17.4"}}}\n' > package-lock.json
osv-scanner scan -r --format json --output-file osv.json ./ || true
jq '.results[0].packages[0].vulnerabilities[0] | {id, sev: .database_specific.severity, events: [.affected[].ranges[].events]}' osv.json
```

Expected: a non-empty `id`, and either a populated `sev` OR (if the record only carries a CVSS vector) `sev == null`. If `--output-file` is rejected, the v2 flag is `--output`; if severity for a High finding comes back `null`, widen the gate's `jq` severity expression to also read `.affected[]?.database_specific.severity` and re-run Task 1's test. Fix the workflow/gate to match reality, then re-run `bash template-tests/test_sca.sh` (still PASS). Delete `/tmp/sca-probe`.

- [ ] **Step 5: Run the SCA test to verify it passes**

Run: `bash template-tests/test_sca.sh`
Expected: PASS — all Task 1 and Task 2 assertions print `ok`, ending `ALL PASS`.

- [ ] **Step 6: Verify the action-pin lockstep test stays green**

`sca.yml` uses `actions/checkout@v7` (the version the core and every template already share). Confirm no drift or float:

Run: `bash template-tests/test_action_pins.sh`
Expected: PASS — `actions/checkout is v7 in the core and in every template`, and "every action is pinned to an explicit version, none float".

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/sca.yml template-tests/test_sca.sh
git commit -m "feat: sca workflow — verified osv-scanner install, scan, apply the policy gate"
```

---

### Task 3: Bake `sca` into the required status checks

`sca.yml` ships into every generated repo (core workflow), so its context always reports — which makes it safe to bake into the shared ruleset exactly like `secret-scan`, rather than adding it dynamically in `apply-rulesets.sh`.

**Files:**
- Modify: `.github/rulesets/repo-ruleset.json:37-44`
- Modify: `template-tests/test_rulesets.sh:100-101`

**Interfaces:**
- Consumes: the `sca` job from Task 2 (`context_reachable` in `test_rulesets.sh` verifies the context resolves to a real non-matrix job).

- [ ] **Step 1: Update the expected required-context set (failing assertion first)**

In `template-tests/test_rulesets.sh`, the block at lines 98-101 sorts the repo ruleset's required contexts and compares to a fixed set. Change the expected set from `{guard-base-branch, secret-scan}` to include `sca` (sorted order is `guard-base-branch`, `sca`, `secret-scan`):

Replace:

```bash
expected=$(printf 'guard-base-branch\nsecret-scan')
```

with:

```bash
expected=$(printf 'guard-base-branch\nsca\nsecret-scan')
```

- [ ] **Step 2: Run the ruleset test to verify it fails**

Run: `bash template-tests/test_rulesets.sh`
Expected: FAIL — `REPO_RULESET required contexts == {...}` fails (`expected 'guard-base-branch\nsca\nsecret-scan', got 'guard-base-branch\nsecret-scan'`).

- [ ] **Step 3: Add the `sca` context to the ruleset**

In `.github/rulesets/repo-ruleset.json`, extend the `required_status_checks` array (currently `guard-base-branch`, `secret-scan`):

```json
        "required_status_checks": [
          {
            "context": "guard-base-branch"
          },
          {
            "context": "secret-scan"
          },
          {
            "context": "sca"
          }
        ]
```

- [ ] **Step 4: Run the ruleset test to verify it passes**

Run: `bash template-tests/test_rulesets.sh`
Expected: PASS — required contexts now match `{guard-base-branch, sca, secret-scan}`, and the reachability check reports `reachable: .github/workflows/sca.yml declares a non-matrix job 'sca'`. Ends `ALL PASS`.

- [ ] **Step 5: Verify the payload the apply script would send includes `sca`**

`apply-rulesets.sh` copies `repo-ruleset.json` as its payload base (line 77), so no script change is needed. Sanity-check the payload logic still resolves:

Run: `jq -r '.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context' .github/rulesets/repo-ruleset.json`
Expected output (order as written):
```
guard-base-branch
secret-scan
sca
```

- [ ] **Step 6: Commit**

```bash
git add .github/rulesets/repo-ruleset.json template-tests/test_rulesets.sh
git commit -m "feat: require the 'sca' status check (baked in, like secret-scan)"
```

---

### Task 4: Prove the SCA files ship into generated repos (and the test does not)

No `init-repo.sh` code change is required — the SCA files fall outside every strip. This task adds assertions so that stays true and cannot silently regress.

**Files:**
- Modify: `template-tests/test_init_repo.sh` (add to the generated-tree assertion block near lines 41-42 and 87)

**Interfaces:**
- Consumes: the generated working tree that `test_init_repo.sh` already builds and asserts against.

- [ ] **Step 1: Add the ship/strip assertions**

In `template-tests/test_init_repo.sh`, immediately after line 42 (`assert_file "secret-scan.yml survived" ...`), add:

```bash
assert_file "sca.yml survived (core workflow, ships into generated repos)" .github/workflows/sca.yml
assert_file "sca-policy.json survived" .github/sca-policy.json
assert_file "sca-gate.sh survived" scripts/sca-gate.sh
```

And after line 35 (`assert_no_dir "template-tests/ removed from working tree" template-tests`), add:

```bash
assert_no_file "the template's own test_sca.sh did not ship (it lives in template-tests/)" template-tests/test_sca.sh
```

- [ ] **Step 2: Run the init-repo test to verify it passes**

Run: `bash template-tests/test_init_repo.sh`
Expected: PASS — the new `assert_file`/`assert_no_file` lines print `ok` alongside the existing generated-tree assertions. Ends `ALL PASS`.

- [ ] **Step 3: Commit**

```bash
git add template-tests/test_init_repo.sh
git commit -m "test: assert the SCA files ship into generated repos and the self-test does not"
```

---

### Task 5: Auto-remediation step + the stated boundary (docs, pinned to a test)

Turn on the signal-to-fix path (a repo setting → adoption playbook) and record the tier-currency boundary. Tie both to `test_sca.sh` so the prose cannot silently vanish.

**Files:**
- Modify: `docs/ADOPTION.md` (section 1)
- Modify: `scripts/init-repo.sh` ("Done. Next:" epilogue, lines 386-392)
- Modify: `SECURITY.md`
- Modify: `template-tests/test_sca.sh` (append two doc assertions)

- [ ] **Step 1: Append the failing doc assertions to `template-tests/test_sca.sh`**

Insert immediately **before** the final `finish` line of `template-tests/test_sca.sh`:

```bash
# --- the stated boundary and the auto-remediation step are documented (not just in the plan) ---
echo "docs: the SCA tier boundary and the auto-remediation step are recorded"
assert_match "SECURITY.md states the tier-currency boundary" 'tier is only as current' "$(cat SECURITY.md)"
assert_match "ADOPTION.md documents enabling Dependabot security updates" 'automated-security-fixes' "$(cat docs/ADOPTION.md)"
```

- [ ] **Step 2: Run the test to verify the new assertions fail**

Run: `bash template-tests/test_sca.sh`
Expected: FAIL — the two new `assert_match` lines fail (the strings are not in the docs yet).

- [ ] **Step 3: Add the tier boundary to `SECURITY.md`**

Append to `SECURITY.md` (after the final section):

```markdown
## The SCA tier is only as current as the last person who set it — ACCEPTED, NOT MITIGATED

`.github/sca-policy.json` carries the dependency-scanning tier. Default `client-facing`: the `sca`
check blocks CI on High/Critical vulnerabilities **that have a fix**. `internal`: warns only. The file
is CODEOWNERS-guarded, so loosening it to `internal` takes a reviewed PR — it cannot be flipped
silently under deadline pressure.

But exposure changes over a repo's life: an internal tool can grow a public surface. **The tier is
only as current as the last person who set it.** The template makes the setting visible and reviewed;
it cannot keep it *correct* as the product changes. Re-check the tier when a repo's exposure changes —
nothing else will.

Neither tier ever blocks on a finding with **no available fix**. That is deliberate: a new CVE against
an already-pinned dependency must not make every open PR unmergeable over something nobody can fix.
No-fix findings warn; Dependabot security updates (enabled at adoption) open the fix PR when one
exists, which is what turns the signal into an action.
```

- [ ] **Step 4: Add the auto-remediation gated step to `docs/ADOPTION.md`**

In `docs/ADOPTION.md` section 1, after step 4 (`next` stack — link Vercel), insert a new step and renumber the current step 5 ("Fill in the skeleton") to 6. Replace the existing step 5 block:

```markdown
5. **Fill in the skeleton.** Complete the `<!-- TODO -->` markers in `README.md` and `CLAUDE.md`, and
   install the local hook: `pre-commit install`.
```

with:

```markdown
5. **Turn on dependency auto-remediation.** So a known-vulnerable dependency arrives as an open fix
   PR, not a bare red `sca` check, enable Dependabot alerts and security updates:

       REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
       gh api -X PUT "repos/${REPO}/vulnerability-alerts"
       gh api -X PUT "repos/${REPO}/automated-security-fixes"

   This is a repository **setting**, not a committed file — it cannot live in `dependabot.yml`, so it
   is a deliberate one-time step here (same class as `apply-rulesets.sh`). The `sca` check enforces
   the tier in `.github/sca-policy.json` (default `client-facing`: blocks CI on High/Critical vulns
   **that have a fix**); these settings make that fix show up automatically. Downgrading the tier to
   `internal` is a reviewed edit to that CODEOWNERS-guarded file — see `SECURITY.md`.

6. **Fill in the skeleton.** Complete the `<!-- TODO -->` markers in `README.md` and `CLAUDE.md`, and
   install the local hook: `pre-commit install`.
```

- [ ] **Step 5: Point the generated repo's epilogue at the same step**

Because `docs/ADOPTION.md` is removed at adoption, the adopter's last on-screen instructions are `init-repo.sh`'s "Done. Next:" list. Add the Dependabot-enable line there. In `scripts/init-repo.sh`, replace the epilogue (lines 386-392):

```bash
cat <<EOF

Done. Next:
  1. pre-commit install
  2. Fill in the TODOs in README.md and CLAUDE.md
  3. ./scripts/apply-rulesets.sh          # adds 'ci' to required checks now that ci.yml exists
EOF
```

with:

```bash
cat <<EOF

Done. Next:
  1. pre-commit install
  2. Fill in the TODOs in README.md and CLAUDE.md
  3. ./scripts/apply-rulesets.sh          # adds 'ci' to required checks now that ci.yml exists
  4. Enable Dependabot security updates (a repo setting — turns 'sca' findings into fix PRs):
       REPO="\$(gh repo view --json nameWithOwner -q .nameWithOwner)"
       gh api -X PUT "repos/\${REPO}/vulnerability-alerts"
       gh api -X PUT "repos/\${REPO}/automated-security-fixes"
EOF
```

(The `\$` / `\${` escaping keeps the expansion in the adopter's shell, not in `init-repo.sh`'s heredoc.)

- [ ] **Step 6: Run the SCA test to verify the doc assertions pass**

Run: `bash template-tests/test_sca.sh`
Expected: PASS — the two doc `assert_match` lines print `ok`; everything from Tasks 1-2 still passes. Ends `ALL PASS`.

- [ ] **Step 7: Verify `init-repo.sh` still parses (no heredoc breakage)**

Run: `bash -n scripts/init-repo.sh && shellcheck scripts/init-repo.sh`
Expected: no syntax error; only pre-existing, unrelated shellcheck warnings (if any).

- [ ] **Step 8: Commit**

```bash
git add SECURITY.md docs/ADOPTION.md scripts/init-repo.sh template-tests/test_sca.sh
git commit -m "docs: SCA tier boundary (SECURITY.md) + enable Dependabot security updates at adoption"
```

---

### Task 6: Full-suite green + shellcheck (integration gate)

**Files:** none (verification only).

- [ ] **Step 1: Run the entire template-tests suite**

Run: `for t in template-tests/test_*.sh; do echo "== $t =="; bash "$t" || exit 1; done`
Expected: every suite ends `ALL PASS`; the loop exits 0. (`test_sca.sh`, `test_rulesets.sh`, `test_init_repo.sh`, `test_action_pins.sh` are the ones this plan touches; the rest must remain green.)

- [ ] **Step 2: shellcheck the new/changed shell**

Run: `shellcheck scripts/sca-gate.sh scripts/init-repo.sh template-tests/test_sca.sh`
Expected: no new findings.

- [ ] **Step 3: Confirm no action floats and pins are in lockstep (belt-and-suspenders)**

Run: `bash template-tests/test_action_pins.sh`
Expected: `ALL PASS`.

---

## Self-Review

**1. Spec coverage (design Item 1 + §Testing):**
- Two tiers + invariant + fail-safe default → Task 1 (gate + policy) and its tests. ✔
- Auto-remediation (Dependabot security updates) as a gated adoption step → Task 5 (ADOPTION.md + epilogue). ✔
- Committed, CODEOWNERS-guarded policy value → `.github/sca-policy.json` under the `*` CODEOWNERS wildcard (Task 1); boundary recorded in SECURITY.md (Task 5). ✔
- `osv-scanner` today, language-agnostic, applying the tier threshold → Task 2 workflow + Task 1 gate. ✔
- Stated boundary in SECURITY.md → Task 5. ✔
- §Testing (a) default tier `client-facing` → `test_sca.sh` Step 1 assertion. ✔
- §Testing (b) policy present + referenced by workflow → `test_sca.sh` Task 2 assertions. ✔
- §Testing (c) invariant encoded in threshold logic, not prose → `test_sca.sh` gate exit-code tests (Task 1). ✔
- §Testing optional negative test (tests removed → `ci` red) belongs to **Item 2** (runner-integrity), which is out of scope for this plan.
- **Open decision resolved:** policy shape = a dedicated committed `.github/sca-policy.json` (JSON, `jq`-parsed, mirrors `vercel.json`); recorded here as the chosen option per the design's instruction that "the plan picks one."

**2. Placeholder scan:** No `TBD`/`TODO`/"handle edge cases"/"similar to Task N". Every code step contains full file content or an exact before→after replacement. The one genuinely uncertain external fact (osv-scanner's live JSON schema/flags) is handled by an explicit empirical verification step (Task 2 Step 4) rather than a guess, with the concrete corrective action stated.

**3. Type/name consistency:** `scripts/sca-gate.sh <osv-json> <policy-json>` and `.github/sca-policy.json` `.tier` are used identically across Tasks 1, 2, 5. The required context, workflow `name:`, and job key are all `sca` (Tasks 2, 3). The severity path `.database_specific.severity` and fix path `.affected[].ranges[].events[].fixed` match between the gate script and the test fixtures (Task 1).

## Execution Handoff — see the assistant message accompanying this plan.
