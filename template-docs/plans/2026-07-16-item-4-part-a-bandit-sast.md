# Item 4 Part A — Bandit SAST for the `python` stack — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-party Bandit SAST to the `python` stack's CI so that a High-severity **and** High-confidence finding blocks the already-required `ci` check on `client-facing` repos, and warns on `internal` — with no GitHub Advanced Security, no network egress, and no new required status context.

**Architecture:** A `bandit` sibling job is added to `templates/python/.github/workflows/ci.yml`. Its verdict reaches the merge gate only because the `ci` aggregate job's gate step is extended to fail when `needs.bandit.result != "success"` (a bare `needs:` does **not** gate — the `ci` job runs `if: always()`, deliberately decoupled from needs-failure). The tier/threshold logic lives in `scripts/bandit-gate.sh` and the aggregate verdict in `scripts/ci-aggregate-gate.sh` — both driven directly by `template-tests/`, mirroring the repo's `check-base-branch.sh` / `sca-gate.sh` convention ("exercise the same script the workflow runs, not a copy"). Tier is read from Item 1's **shared** `.github/sca-policy.json` (kept, not renamed — see Global Constraints).

**Tech Stack:** Bash + `jq` (gate scripts), Bandit (PyCQA, Apache-2.0, PyPI, offline), GitHub Actions, the `template-tests/` bash suite.

## Global Constraints

- **Base branch:** this work is **stacked on `feat/sca-dependency-scanning`** (which carries Item 1's `.github/sca-policy.json`, `scripts/sca-gate.sh`, `sca.yml`, `SECURITY.md` tier boundary). Part A **must not merge ahead of Item 1** — its PR targets `dev` but merges after Item 1's. Carry the two Item-4 spec commits (`f74b081`, `75f5cdb`) along.
- **Policy file:** reuse Item 1's **`.github/sca-policy.json`** verbatim. Do **not** create a second policy/tier file and do **not** rename it. Document the shared-tier reuse with a comment at both call sites (`scripts/sca-gate.sh` header and `scripts/bandit-gate.sh` header).
- **Tier key:** confirmed present on the base branch — `.github/sca-policy.json` → `.tier`, values `client-facing` (default) | `internal`, gate fail-safes to `client-facing` on a missing/invalid tier.
- **Block rule (Part A's new axis):** block **only** on `issue_severity == "HIGH"` **AND** `issue_confidence == "HIGH"`. This confidence axis is a false-positive filter, **not** Item 1's fix-availability invariant — label it as such, do not smuggle it in as inheritance.
- **No new required context:** ride the existing `ci` context. Add nothing to `scripts/apply-rulesets.sh` or the rulesets. `ci.yml` is stack-scoped, so `node`/`next` never carry the `bandit` job.
- **No network egress:** Bandit installs from PyPI and makes no calls at scan time. No token, no registry, no cloud.
- **Config home:** Bandit tool config lives in `pyproject.toml` `[tool.bandit]` (the stack already puts ruff/mypy/pytest there).
- **Suppression:** in-code `# nosec <TEST_ID>`, reviewed in the diff. Named in `SECURITY.md` as a silent, un-expiring hole.
- **Parts B (CodeQL) and C (org rollout research) are OUT OF SCOPE** — Team-gated, no dormant file committed. The spec is their record.

---

## File Structure

- `scripts/bandit-gate.sh` **(create)** — applies the tier + high/high threshold to a Bandit JSON report; sets the check exit code. One responsibility: turn a Bandit report + policy into a verdict.
- `scripts/ci-aggregate-gate.sh` **(create)** — the `ci` job's hand-rolled aggregate verdict, extracted from inline YAML so it is testable: any `<label>:<result>` pair whose result is not `success` fails the check.
- `templates/python/.github/workflows/ci.yml` **(modify)** — add the `bandit` job; add `bandit` to the `ci` job's `needs`; replace the `ci` gate step's inline bash with a call to `scripts/ci-aggregate-gate.sh`.
- `templates/python/pyproject.toml` **(modify)** — add `[tool.bandit]` (config home + skip-list location).
- `SECURITY.md` **(modify)** — add the two SAST boundaries + the suppression rot-risk note, in the existing tier-boundary idiom.
- `template-tests/test_bandit.sh` **(create)** — the required Part A assertions (a)–(e); auto-registered by the `template-tests/test_*.sh` glob.

---

### Task 1: `scripts/bandit-gate.sh` — the tier + high/high verdict

**Files:**
- Create: `scripts/bandit-gate.sh`
- Create: `template-tests/test_bandit.sh`
- Modify: `scripts/sca-gate.sh` (one-line reuse comment only)

**Interfaces:**
- Consumes: `.github/sca-policy.json` → `.tier` (Item 1, present on base branch); `jq`.
- Produces: `scripts/bandit-gate.sh <bandit-json> <policy-json>` → exit `1` iff (tier is `client-facing` **and** ≥1 finding is `issue_severity==HIGH && issue_confidence==HIGH`); exit `0` otherwise (warn / nothing / internal); exit `2` on missing `jq`.

- [ ] **Step 1: Write the failing test** — `template-tests/test_bandit.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=template-tests/lib.sh disable=SC1091
source template-tests/lib.sh

# =======================================================================================
# Item 4 Part A — Bandit SAST. The BLOCK RULE is the whole point and it lives in a test,
# not in prose: scripts/bandit-gate.sh is driven with recorded Bandit-shaped JSON and the
# EXIT CODE is asserted. Block ONLY on HIGH severity AND HIGH confidence, and ONLY on the
# 'client-facing' tier (read from Item 1's shared .github/sca-policy.json).

GATE=scripts/bandit-gate.sh
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# --- policy fixtures (reuse Item 1's schema: {"tier": ...}) -----------------------------
printf '{"tier":"client-facing"}\n' > "$TMP/client.json"
printf '{"tier":"internal"}\n'      > "$TMP/internal.json"
printf '{"nope":true}\n'            > "$TMP/malformed.json"   # no tier -> must default to strict

# --- bandit report fixtures (shape of `bandit -f json`: results[].issue_severity/_confidence) ---
mk() { # <severity> <confidence> -> a one-finding bandit report on stdout
  printf '{"errors":[],"results":[{"test_id":"B602","test_name":"x","filename":"src/app/a.py","line_number":3,"issue_severity":"%s","issue_confidence":"%s","issue_text":"t"}]}\n' "$1" "$2"
}
mk HIGH HIGH   > "$TMP/high_high.json"
mk HIGH LOW    > "$TMP/high_low.json"     # confidence axis: severity high, confidence low -> no block
mk LOW  HIGH   > "$TMP/low_high.json"     # severity axis: confidence high, severity low  -> no block
mk MEDIUM MEDIUM > "$TMP/med_med.json"
printf '{"errors":[],"results":[]}\n' > "$TMP/clean.json"

gate_rc() { local rc=0; "$GATE" "$1" "$2" >/dev/null 2>&1 || rc=$?; echo "$rc"; }

echo "bandit-gate: block ONLY on high severity AND high confidence, ONLY on client-facing"
assert_eq 1 "$(gate_rc "$TMP/high_high.json" "$TMP/client.json")"   "client-facing blocks a HIGH-severity + HIGH-confidence finding"
assert_eq 0 "$(gate_rc "$TMP/high_high.json" "$TMP/internal.json")" "internal only warns on the same high/high finding"
assert_eq 0 "$(gate_rc "$TMP/high_low.json"  "$TMP/client.json")"   "client-facing does NOT block HIGH severity + LOW confidence (confidence axis)"
assert_eq 0 "$(gate_rc "$TMP/low_high.json"  "$TMP/client.json")"   "client-facing does NOT block LOW severity + HIGH confidence (severity axis)"
assert_eq 0 "$(gate_rc "$TMP/med_med.json"   "$TMP/client.json")"   "client-facing does NOT block a MEDIUM/MEDIUM finding"
assert_eq 0 "$(gate_rc "$TMP/clean.json"     "$TMP/client.json")"   "a clean report (no findings) passes"
assert_eq 1 "$(gate_rc "$TMP/high_high.json" "$TMP/malformed.json")" "a policy with no valid tier defaults to client-facing (strict) and still blocks (fail-safe)"
assert_eq 0 "$(gate_rc "$TMP/does-not-exist.json" "$TMP/client.json")" "a missing/empty bandit report passes (nothing to gate)"

# --- design §Testing (b): reads its TIER from Item 1's committed policy file, no 2nd tier dial ---
echo "bandit-gate: reads the shared Item 1 policy file; adds no second tier file"
assert_match "bandit-gate.sh reads .github/sca-policy.json"  '\.github/sca-policy\.json' "$(cat "$GATE")"
assert_no_file "Part A must NOT introduce a second policy/tier file" .github/security-policy.json
assert_file   "the shared Item 1 policy file is present on the base branch" .github/sca-policy.json
assert_eq "client-facing" "$(jq -r '.tier' .github/sca-policy.json)" "the shipped shared tier is the fail-safe 'client-facing'"

# --- fidelity: if real bandit is available, prove our fixtures match its actual JSON schema ---
echo "bandit-gate: real-bandit fidelity (skipped if bandit is not installed)"
if command -v bandit >/dev/null 2>&1; then
  mkdir -p "$TMP/proj"
  # B602 (subprocess with shell=True) is Bandit HIGH severity / HIGH confidence.
  printf 'import subprocess\ndef run(c):\n    subprocess.Popen(c, shell=True)\n' > "$TMP/proj/x.py"
  bandit -r "$TMP/proj" -f json -o "$TMP/real.json" >/dev/null 2>&1 || true
  assert_eq "HIGH" "$(jq -r '[.results[]|select(.issue_severity=="HIGH" and .issue_confidence=="HIGH")][0].issue_severity // "NONE"' "$TMP/real.json")" "real bandit emits a HIGH/HIGH finding for shell=True (schema matches our fixtures)"
  assert_eq 1 "$(gate_rc "$TMP/real.json" "$TMP/client.json")" "the gate blocks a REAL bandit high/high report on client-facing"
else
  skip "bandit not installed — schema-fidelity check not run"
fi

finish
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `bash template-tests/test_bandit.sh`
Expected: FAIL — the first assertions error because `scripts/bandit-gate.sh` does not exist (`gate_rc` returns a non-`0/1` code / the `assert_match` on its contents fails).

- [ ] **Step 3: Write `scripts/bandit-gate.sh`**

```bash
#!/usr/bin/env bash
# scripts/bandit-gate.sh <bandit-json> <policy-json>
#
# Applies the SAST policy tier to a Bandit (`-f json`) report and sets the check verdict.
#
# THE BLOCK RULE (client-facing only): block ONLY on a finding that is BOTH high severity AND high
# confidence. This confidence axis is Part A's OWN dial — a false-positive filter for pattern SAST,
# NOT a reuse of Item 1's fix-availability invariant (that axis is about whether a finding is
# actionable; this one is about whether it is real). Requiring high-confidence-too collapses the
# volume to the handful a small team can actually own.
#
#   client-facing -> exit 1 if any HIGH-severity AND HIGH-confidence finding; else 0 (warn)
#   internal      -> always exit 0 (warn only)
#
# TIER is read from the SHARED .github/sca-policy.json — Item 1's file. The name says 'sca' but the
# tier dial is stack-neutral and deliberately reused here (see the matching note in sca-gate.sh).
set -euo pipefail

BANDIT_JSON="${1:?usage: bandit-gate.sh <bandit-json> <policy-json>}"
POLICY="${2:?usage: bandit-gate.sh <bandit-json> <policy-json>}"

command -v jq >/dev/null 2>&1 || { echo "::error::jq is required but not installed" >&2; exit 2; }

# Fail-safe: an unreadable or tier-less policy is treated as the STRICT default, never as a bypass.
tier="$(jq -r '.tier // empty' "${POLICY}" 2>/dev/null || true)"
case "${tier}" in
  client-facing|internal) ;;
  *) echo "::warning::sca-policy tier missing/invalid ('${tier:-}') — defaulting to client-facing (strict)"; tier="client-facing" ;;
esac

# An absent/empty report is "nothing to gate" — a clean pass. Bandit writes a report even with zero
# findings, so an empty file here means the job never produced one; the workflow (not the gate) is
# responsible for failing on a real bandit ERROR (see ci.yml).
if [ ! -s "${BANDIT_JSON}" ]; then
  echo "bandit: no report to gate — nothing to do"
  exit 0
fi

# Coverage honesty: files bandit could not parse land in .errors. Surface them; do not block on them.
errs="$(jq -r '(.errors // []) | length' "${BANDIT_JSON}" 2>/dev/null || echo 0)"
if [ "${errs}" -gt 0 ]; then
  echo "::warning::bandit reported ${errs} scan error(s) (unparseable files) — those files were NOT scanned"
fi

# All findings, for the informational warn line (every severity/confidence).
all="$(jq -r '[ .results[]? | "\(.test_id) \(.issue_severity)/\(.issue_confidence) \(.filename):\(.line_number)" ] | .[]' "${BANDIT_JSON}")"
if [ -n "${all}" ]; then
  echo "bandit: findings (all severities/confidences):"
  while IFS= read -r line; do printf '  - %s\n' "${line}"; done <<<"${all}"
fi

# A "blocking" finding = HIGH severity AND HIGH confidence. Both axes, ANDed.
blocking="$(jq -r '[ .results[]? | select(.issue_severity == "HIGH" and .issue_confidence == "HIGH") | "\(.test_id) \(.filename):\(.line_number)" ] | .[]' "${BANDIT_JSON}")"

if [ -z "${blocking}" ]; then
  echo "bandit: no HIGH-severity AND HIGH-confidence finding — nothing blocks (tier: ${tier})"
  exit 0
fi

echo "::group::bandit: HIGH-severity AND HIGH-confidence findings"
while IFS= read -r line; do printf '  - %s\n' "${line}"; done <<<"${blocking}"
echo "::endgroup::"

if [ "${tier}" = "client-facing" ]; then
  echo "::error::bandit gate (client-facing): the finding(s) above are HIGH severity AND HIGH confidence. Fix them, or suppress with an in-code '# nosec <TEST_ID>' (reviewed in the diff) to clear this check."
  exit 1
fi

echo "::warning::bandit gate (internal): high/high findings exist, but this repo's tier is 'internal' — warning only, not blocking."
exit 0
```

- [ ] **Step 4: Make it executable + add the reuse comment in `sca-gate.sh`**

```bash
chmod +x scripts/bandit-gate.sh
```

In `scripts/sca-gate.sh`, immediately after the `POLICY="${2:?...}"` line, add the reciprocal note so the shared file is documented at **both** call sites:

```bash
# NOTE: .github/sca-policy.json's `.tier` is SHARED — scripts/bandit-gate.sh (Item 4 SAST) reads the
# same dial. The file name says 'sca' but the tier is stack-neutral; both gates honour it. See
# SECURITY.md. If this is ever renamed, update bandit-gate.sh, sca.yml, ci.yml and both test suites.
```

- [ ] **Step 5: Run the test to confirm it passes**

Run: `bash template-tests/test_bandit.sh`
Expected: PASS (`ALL PASS`). The fidelity block prints `SKIP` if `bandit` is not installed locally — that is a pass, not a failure.

- [ ] **Step 6: Commit**

```bash
git add scripts/bandit-gate.sh scripts/sca-gate.sh template-tests/test_bandit.sh
git commit -m "feat: bandit-gate.sh — high/high SAST verdict on the shared tier"
```

---

### Task 2: Wire Bandit into the `python` `ci.yml` so it reddens the required `ci` check

**Files:**
- Create: `scripts/ci-aggregate-gate.sh`
- Modify: `templates/python/.github/workflows/ci.yml`
- Modify: `template-tests/test_bandit.sh` (append the wiring + node/next + (e) assertions)

**Interfaces:**
- Consumes: `scripts/bandit-gate.sh` (Task 1); `.github/sca-policy.json`.
- Produces: `scripts/ci-aggregate-gate.sh <label>:<result> [...]` → exit `1` if any `<result> != success` (else `0`, else `2` on no args). The `python` `ci.yml` gains a `bandit` job and its `ci` gate calls this script with `test:` and `bandit:` results.

- [ ] **Step 1: Append the failing wiring + coverage tests to `template-tests/test_bandit.sh`**

Insert **before** the final `finish` line:

```bash
# =======================================================================================
# §Testing (e): a seeded high/high finding must turn the required `ci` CONTEXT red on
# client-facing and green on internal. `ci` reddens ONLY through scripts/ci-aggregate-gate.sh,
# so drive it directly (the guard-base-branch pattern) and COMPOSE it with the bandit verdict.
CIGATE=scripts/ci-aggregate-gate.sh
ci_gate_rc() { local rc=0; "$CIGATE" "$@" >/dev/null 2>&1 || rc=$?; echo "$rc"; }

echo "ci-aggregate-gate: any non-success job result reddens the ci check"
assert_eq 0 "$(ci_gate_rc "test:success" "bandit:success")"  "all jobs success -> ci green"
assert_eq 1 "$(ci_gate_rc "test:success" "bandit:failure")"  "bandit failed -> ci red"
assert_eq 1 "$(ci_gate_rc "test:failure" "bandit:success")"  "test failed -> ci red (existing invariant preserved)"

echo "ci context (e): high/high blocks the CI check on client-facing, warns on internal"
# client-facing: bandit-gate blocks -> the bandit JOB would be 'failure' -> ci gate reddens.
brc="$(gate_rc "$TMP/high_high.json" "$TMP/client.json")"; assert_eq 1 "$brc" "client-facing: bandit job fails on high/high"
bres="$([ "$brc" -eq 0 ] && echo success || echo failure)"
assert_eq 1 "$(ci_gate_rc "test:success" "bandit:$bres")" "client-facing high/high turns the required 'ci' check RED"
# internal: bandit-gate warns -> the bandit JOB is 'success' -> ci gate stays green.
brc="$(gate_rc "$TMP/high_high.json" "$TMP/internal.json")"; assert_eq 0 "$brc" "internal: bandit job succeeds (warn only) on high/high"
bres="$([ "$brc" -eq 0 ] && echo success || echo failure)"
assert_eq 0 "$(ci_gate_rc "test:success" "bandit:$bres")" "internal high/high leaves the 'ci' check GREEN"

echo "ci.yml wiring: the python ci job actually gates on bandit's result"
PYCI=templates/python/.github/workflows/ci.yml
pyci="$(cat "$PYCI")"
assert_match "python ci.yml declares a 'bandit:' job"                 '^[[:space:]]*bandit:[[:space:]]*$' "$pyci"
assert_match "python ci.yml runs scripts/bandit-gate.sh"             'scripts/bandit-gate\.sh'           "$pyci"
assert_match "python ci job 'needs' includes bandit"                  'needs:.*bandit'                    "$pyci"
assert_match "python ci gate calls scripts/ci-aggregate-gate.sh"     'scripts/ci-aggregate-gate\.sh'     "$pyci"
assert_match "python ci gate passes needs.bandit.result to the gate"  'needs\.bandit\.result'             "$pyci"

echo "no-hang property (d): node and next carry NO bandit job, but their ci context still reports"
for stack in node next; do
  wf="templates/$stack/.github/workflows/ci.yml"
  assert_file "$stack has a ci.yml" "$wf"
  txt="$(cat "$wf")"
  assert_nomatch "$stack ci.yml has NO bandit job" '^[[:space:]]*bandit:[[:space:]]*$' "$txt"
  assert_nomatch "$stack ci.yml never runs bandit-gate.sh" 'bandit-gate\.sh' "$txt"
  assert_match   "$stack ci.yml still declares a 'ci:' job (context reports)" '^[[:space:]]*ci:[[:space:]]*$' "$txt"
done
```

- [ ] **Step 2: Run it to confirm the new assertions fail**

Run: `bash template-tests/test_bandit.sh`
Expected: FAIL — `ci-aggregate-gate.sh` does not exist yet, and `ci.yml` has no `bandit` job / no `ci-aggregate-gate.sh` call.

- [ ] **Step 3: Write `scripts/ci-aggregate-gate.sh`**

```bash
#!/usr/bin/env bash
# scripts/ci-aggregate-gate.sh <label>:<result> [<label>:<result> ...]
#
# The 'ci' job is a bare aggregate whose ONLY purpose is to turn the required 'ci' check red when an
# upstream job failed. A plain `needs:` does NOT do that here: the 'ci' job runs `if: always()` (so
# it still reports when the matrix fails), and `if: always()` deliberately DECOUPLES the job from
# needs-failure. So the verdict is hand-rolled: any job whose result is not exactly "success" fails
# the check. Adding a job to `needs:` is necessary but NOT sufficient — it must also be named here.
#
# This lives in a script (not inline YAML) so template-tests can exercise the SAME logic the
# workflow runs — the scripts/check-base-branch.sh / guard-base-branch pattern.
set -euo pipefail

[ "$#" -ge 1 ] || { echo "usage: ci-aggregate-gate.sh <label>:<result> ..." >&2; exit 2; }

failed=0
for pair in "$@"; do
  label="${pair%%:*}"
  result="${pair#*:}"
  if [ "${result}" = "success" ]; then
    echo "ok: '${label}' succeeded"
  else
    echo "::error::the '${label}' job did not succeed (result: ${result})"
    failed=1
  fi
done

[ "${failed}" -eq 0 ] || exit 1
echo "all required jobs passed"
```

```bash
chmod +x scripts/ci-aggregate-gate.sh
```

- [ ] **Step 4: Modify `templates/python/.github/workflows/ci.yml`**

Add the `bandit` job after the `test` job (before `ci:`). It inherits the file-level `permissions: contents: read`:

```yaml
  # Item 4 Part A — first-party SAST. Bandit walks the Python AST for vulnerability shapes
  # (shell=True, yaml.load, pickle, weak crypto, ...). It is a SIBLING job; its verdict reaches the
  # merge gate only because the `ci` job below is extended to fail on `needs.bandit.result`. A bare
  # `needs:` would NOT gate — see scripts/ci-aggregate-gate.sh. Bandit is offline (no token/registry).
  bandit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      # Version-pinned, manual-bump: an ad-hoc `pip install` is not in a manifest, so Dependabot
      # cannot bump it — the same tradeoff sca.yml makes for the osv-scanner binary. Resolve the
      # current release with `pip index versions bandit` and pin it here.
      - run: pip install "bandit==1.8.6"
      - name: run Bandit and apply the policy
        run: |
          set -euo pipefail
          # Bandit exits 1 when it finds ANY issue and 0 when clean; neither is this gate's verdict
          # (the tier + high/high threshold is applied by bandit-gate.sh), so allow both. Any OTHER
          # exit is a real Bandit error — refuse to report a clean check on a failed scan (fail-safe,
          # the same posture as sca.yml).
          rc=0
          bandit -c pyproject.toml -r src -f json -o bandit.json || rc=$?
          case "${rc}" in
            0|1) ;;
            *) echo "::error::bandit exited ${rc} (not a clean/found-issues code) — failed scan, refusing to report a clean check"; exit "${rc}" ;;
          esac
          scripts/bandit-gate.sh bandit.json .github/sca-policy.json
```

Then extend the `ci` job. Change its `needs:` and replace the inline gate step's `run:` with a call to the script, preserving the existing explanatory comments:

```yaml
  ci:
    # `if: always()` is load-bearing. Without it this job is SKIPPED when the matrix
    # fails, and a skipped required check never reports either — it blocks the merge
    # just as silently as a missing one. Always run; fail loudly on a bad matrix.
    #
    # `needs` alone does NOT gate under `if: always()` — the verdict is hand-rolled in
    # scripts/ci-aggregate-gate.sh, which MUST name every job whose failure should block.
    needs: [test, bandit]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: Gate on the matrix and SAST results
        run: |
          set -euo pipefail
          scripts/ci-aggregate-gate.sh \
            "test:${{ needs.test.result }}" \
            "bandit:${{ needs.bandit.result }}"
```

> Note: the `ci` job previously had no `checkout` step (it only read `needs.*.result`). It now needs one so `scripts/ci-aggregate-gate.sh` is on disk — the added `- uses: actions/checkout@v7` above provides it.

- [ ] **Step 5: Run the test suite to confirm it passes**

Run: `bash template-tests/test_bandit.sh`
Expected: PASS (`ALL PASS`).

- [ ] **Step 6: Sanity-check the workflow YAML parses**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('templates/python/.github/workflows/ci.yml')); print('ci.yml parses')"`
Expected: `ci.yml parses` (no traceback). If `pyyaml` is absent, skip this check.

- [ ] **Step 7: Commit**

```bash
git add scripts/ci-aggregate-gate.sh templates/python/.github/workflows/ci.yml template-tests/test_bandit.sh
git commit -m "feat: wire Bandit into python ci.yml so high/high reddens the required 'ci' check"
```

---

### Task 3: Config home (`[tool.bandit]`) + the stated boundaries in `SECURITY.md`

**Files:**
- Modify: `templates/python/pyproject.toml`
- Modify: `SECURITY.md`
- Modify: `template-tests/test_bandit.sh` (append the docs/config assertions)

**Interfaces:**
- Consumes: nothing new.
- Produces: `[tool.bandit]` config block; two `SECURITY.md` boundary paragraphs asserted by the suite.

- [ ] **Step 1: Append the failing docs/config assertions to `template-tests/test_bandit.sh`**

Insert **before** the final `finish` line:

```bash
echo "config + docs: config home is pyproject.toml, and the boundaries are stated in SECURITY.md"
assert_match "python pyproject.toml declares [tool.bandit] as the config home" '^\[tool\.bandit\]' "$(cat templates/python/pyproject.toml)"
sec="$(cat SECURITY.md)"
assert_match "SECURITY.md states Bandit is AST-pattern, not dataflow" 'AST' "$sec"
assert_match "SECURITY.md names the node/next TypeScript unscanned gap" 'unscanned' "$sec"
assert_match "SECURITY.md names the nosec suppression as a silent hole" 'nosec' "$sec"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `bash template-tests/test_bandit.sh`
Expected: FAIL — `[tool.bandit]` and the `SECURITY.md` boundary text do not exist yet.

- [ ] **Step 3: Add `[tool.bandit]` to `templates/python/pyproject.toml`**

Append after the existing `[tool.mypy]` block:

```toml
[tool.bandit]
# Bandit (Item 4 Part A SAST) config home — the stack keeps tool config here, like ruff/mypy above.
# CI already scopes the scan to first-party source with `bandit -r src`; tests legitimately use
# `assert` and subprocess in ways that are not production risks, so they are not scanned. Suppress an
# individual finding in-code with `# nosec <TEST_ID>` (reviewed in the diff) — see SECURITY.md for
# why a suppression here is a silent, un-expiring hole. Add long-lived, team-agreed skips below.
exclude_dirs = ["tests"]
```

- [ ] **Step 4: Add the boundaries to `SECURITY.md`**

Append a new subsection after the existing SCA tier boundary section:

```markdown
### Bandit SAST: what it does and does not see (`python` stack)

The `python` stack's CI runs **Bandit**, which walks the Python **AST** for vulnerability *shapes* —
`shell=True`/`subprocess` injection, `yaml.load`, `pickle`, weak crypto, SQL built by string
concatenation, `assert` in production paths. On a `client-facing` repo a finding that is **both High
severity and High confidence** fails the required `ci` check; `internal` warns only. The tier is the
**same** `.github/sca-policy.json` dial the SCA gate reads.

Two boundaries, stated plainly:

1. **Bandit is AST-pattern analysis, not cross-file dataflow.** It flags shapes, not proven exploit
   paths, and it will both *miss* real dataflow bugs and *false-positive* on safe patterns. The
   High-confidence half of the block rule trims the false positives; it does not add dataflow.
2. **Bandit sees the `python` stack only.** The `node` and `next` stacks' first-party TypeScript is
   **unscanned** until CodeQL lands at the GitHub Team cutover (Item 4 Part B). This gap is named,
   not hidden — a failure to verify is not a verified pass.

**Suppression is a silent hole.** A `# nosec <TEST_ID>` (or a `[tool.bandit]` skip) is un-expiring
and, with no Security-tab dismissal trail on Free, the *only* control on it is code review of the
diff that adds it. Treat every new `# nosec` as a reviewed decision, not a convenience.
```

- [ ] **Step 5: Run the full Bandit suite to confirm it passes**

Run: `bash template-tests/test_bandit.sh`
Expected: PASS (`ALL PASS`).

- [ ] **Step 6: Run the entire template-tests suite (nothing else regressed)**

Run: `for t in template-tests/test_*.sh; do echo "== $t =="; bash "$t" || echo "FAILED: $t"; done`
Expected: every suite ends `ALL PASS`; no `FAILED:` line. (`test_sca.sh` still passes — the one-line reuse comment added to `sca-gate.sh` does not change its behavior. Org-access-gated blocks may print `SKIP` locally, which is a pass.)

- [ ] **Step 7: Commit**

```bash
git add templates/python/pyproject.toml SECURITY.md template-tests/test_bandit.sh
git commit -m "docs: Bandit SAST boundaries in SECURITY.md + [tool.bandit] config home"
```

---

## Deferred (recorded, not implemented here)

- **Part B — CodeQL** (Python + TS cross-file dataflow): GitHub Advanced Security, Team-only. No dormant workflow committed. Spec §Part B is the record.
- **Part C — org-ruleset rollout + Q1/Q2 research protocol**: Team-only; verification is the probe results. Spec §Part C is the record.
- Do **not** add a required `bandit` status context, and do **not** touch `scripts/apply-rulesets.sh` — Part A rides the existing `ci` context by design.

---

## Self-Review

**Spec coverage (§Testing (a)–(e) + design decisions):**
- (a) fail-safe `client-facing` default → Task 1 malformed-policy assertion + shipped-tier assertion. ✓
- (b) reads tier from Item 1's committed file, no second dial → Task 1 (`assert_match sca-policy.json`, `assert_no_file security-policy.json`). ✓
- (c) block threshold = HIGH severity AND HIGH confidence, in logic → Task 1 fixtures (high/high, high/low, low/high, med/med). ✓
- (d) node/next carry no `bandit` job while `ci` still reports → Task 2 loop over node+next. ✓
- (e) seeded high/high reddens the **`ci` context** on client-facing, green on internal → Task 2 composed `gate_rc` → `ci_gate_rc`, plus wiring greps for `needs.bandit.result` + `ci-aggregate-gate.sh`. ✓
- Confidence axis labeled as Part A's own dial, not Item 1 inheritance → `bandit-gate.sh` header + SECURITY.md. ✓
- Policy-file decision (keep + comment both sites) → Global Constraints + Task 1 Step 4 (`sca-gate.sh` note) + `bandit-gate.sh` header. ✓
- Config location = `pyproject.toml [tool.bandit]` → Task 3. ✓
- Wiring = sibling job + extended `ci` gate (not a dedicated required context) → Task 2. ✓
- Self-contained/offline Bandit; no dormant CodeQL → honored; Parts B/C deferred. ✓

**Placeholder scan:** the only environment-resolved value is the Bandit version pin (`bandit==1.8.6`), with the exact command to confirm/adjust it (`pip index versions bandit`) in the step. No `TBD`/`handle edge cases`/`similar to`.

**Type/name consistency:** `gate_rc`/`ci_gate_rc` helpers, `GATE=scripts/bandit-gate.sh`, `CIGATE=scripts/ci-aggregate-gate.sh`, policy key `.tier`, block rule `issue_severity=="HIGH" && issue_confidence=="HIGH"` — used identically across all three tasks. `ci-aggregate-gate.sh` arg shape `<label>:<result>` matches the `ci.yml` call in Task 2 Step 4.
