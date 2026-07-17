# SHA-Pin GitHub Actions (Hardening Item 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin every GitHub Action in the core and template workflows to an immutable full commit SHA (with a `# vX.Y.Z` comment), and rewrite `test_action_pins.sh` to enforce SHA pins + version comments in lockstep while preserving the branch-ref float guard.

**Architecture:** A version tag (`@v7`) is mutable — a compromised maintainer can repoint it (the 2025 `tj-actions/changed-files` compromise). Replacing all 9 pin occurrences with 40-hex commit SHAs closes that vector. The existing lockstep test (which keeps `templates/` from rotting, since Dependabot is blind to nested `.github/workflows`) is re-keyed from the tag onto the immutable SHA, and gains a shape assertion that rejects any bare tag.

**Tech Stack:** GitHub Actions YAML, Bash test harness (`template-tests/*.sh` + `template-tests/lib.sh`).

## Global Constraints

- **Full 40-hex commit SHA, not a tag or short SHA.** Every remote-action pin is exactly 40 lowercase hex chars, matching what Dependabot emits so it and the test never fight.
- **Precise `# vX.Y.Z` version comment** on every pin (the version the SHA resolves to).
- **SHA-pin the version currently in use — do NOT upgrade.** checkout stays v7, setup-node stays v4, setup-python stays v5. Upgrades are Dependabot's job and out of scope.
- **Lockstep on the SHA:** any action used in both core and a template must be pinned to the *same* SHA.
- **Preserve the float guard:** `@main` / `@master` / `@latest` must still hard-fail.
- **Preserve the vacuity guards:** the suite must fail (not silently pass) if it finds no pins or no shared action.
- **The suite must be green at the end of the single commit** — the repo philosophy is never to land a red suite. Test rewrite and pin conversion land together.

## Resolved pin values (verified via `git ls-remote` on 2026-07-16)

| Action (current tag) | Full SHA | Comment |
|---|---|---|
| `actions/checkout@v7` | `9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0` | `# v7.0.0` |
| `actions/setup-node@v4` | `49933ea5288caeca8642d1e84afbd3f7d6820020` | `# v4.4.0` |
| `actions/setup-python@v5` | `a26af69be951a213d495a4c3e4e4022e16d87065` | `# v5.6.0` |

## File Structure

- **Modify (9 pin lines across 6 workflow files):**
  - `.github/workflows/secret-scan.yml:18` — checkout
  - `.github/workflows/guard-base-branch.yml:27` — checkout
  - `.github/workflows/template-tests.yml:29` — checkout
  - `templates/python/.github/workflows/ci.yml:27,28` — checkout, setup-python
  - `templates/node/.github/workflows/ci.yml:17,18` — checkout, setup-node
  - `templates/next/.github/workflows/ci.yml:20,21` — checkout, setup-node
- **Rewrite:** `template-tests/test_action_pins.sh` — replace the tag-based extraction with SHA-based shape + lockstep checks; keep the float guard and vacuity guards.
- **No change:** `.github/dependabot.yml` (already bumps SHA-pinned actions, updating both SHA and comment), `template-tests/lib.sh`.

---

### Task 1: SHA-pin all actions and re-key the lockstep test onto the SHA

This is a single atomic change: the new test rejects the current tag pins, so it goes red until the pins are converted. TDD-sequenced within the task so an intermediate green is never claimed on the old tree.

**Files:**
- Rewrite: `template-tests/test_action_pins.sh`
- Modify: the 6 workflow files listed above (9 lines total)
- Test: `template-tests/test_action_pins.sh` (the harness under change is its own test)

**Interfaces:**
- Consumes: `template-tests/lib.sh` helpers `pass`, `fail`, `finish` (unchanged signatures).
- Produces: no exported interface; the deliverable is the enforced invariant "every remote action is full-SHA-pinned with a version comment, in lockstep, none floating."

- [ ] **Step 1: Rewrite `template-tests/test_action_pins.sh`** with the full content below.

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=template-tests/lib.sh disable=SC1091
source template-tests/lib.sh

# ---------------------------------------------------------------------------------------
# DEPENDABOT IS BLIND TO templates/. THIS TEST IS WHAT KEEPS THEM FROM ROTTING.
#
# .github/dependabot.yml declares the github-actions ecosystem at `directory: "/"`, and for that
# ecosystem dependabot scans the ROOT .github/workflows ONLY. So it bumps the core workflows
# (guard-base-branch, secret-scan) and NEVER touches:
#
#     templates/python/.github/workflows/ci.yml
#     templates/node/.github/workflows/ci.yml
#     templates/next/.github/workflows/ci.yml
#
# Those files are not workflows *of this repo* — they are payload, copied into a generated repo by
# init-repo.sh, where they land at the root and dependabot finally sees them. Which means: a
# generated repo keeps its actions current, but THE TEMPLATE ITSELF ships whatever version it was
# born with, forever, silently. Every new repo starts life on a stale action.
#
# There is no dependabot config that fixes this (it will not scan a nested .github/workflows for
# the github-actions ecosystem). So the fix is a LOCKSTEP TEST, the same idiom this repo already
# uses to keep the gitleaks version in secret-scan.yml matched to the pre-commit hook:
#
#     any action used in BOTH the core and a template must be pinned to the SAME SHA.
#
# Dependabot bumps the core -> this suite goes red -> whoever merges the dependabot PR must bump
# the templates too. The rot becomes a failing test instead of a silent decay.
#
# SHA-PINNED, NOT TAG-PINNED. A version tag (v7) is MUTABLE: a compromised action maintainer can
# repoint it to malicious code and every consumer picks it up on the next run (the 2025
# tj-actions/changed-files compromise). A commit SHA is immutable and closes that vector. So every
# action is pinned to a full 40-hex commit SHA, with a `# vX.Y.Z` comment for humans and for
# Dependabot (which bumps SHA pins, updating BOTH the SHA and the comment). The lockstep check
# below keys on the SHA — the immutable thing — not the comment.

CORE_WF=(.github/workflows/*.yml)
TMPL_WF=(templates/*/.github/workflows/*.yml)

# ---------------------------------------------------------------------------------------
# Every remote action (owner/repo@ref) must be pinned to a full 40-hex commit SHA AND carry a
# `# vX...` version comment. A bare tag (@v7) fails here — that is the whole point of the change.
echo "action pins: every remote action is pinned to a 40-hex commit SHA with a # vX.Y.Z comment"
shape_seen=0
shape_bad=0
while IFS= read -r hit; do
  [ -n "$hit" ] || continue
  shape_seen=$((shape_seen + 1))
  if ! grep -qE 'uses: *[A-Za-z0-9._-]+/[A-Za-z0-9._-]+@[0-9a-f]{40} +# *v[0-9]' <<<"$hit"; then
    shape_bad=1
    fail "not SHA-pinned with a version comment: ${hit}"
  fi
done < <(grep -rnE 'uses: *[A-Za-z0-9._-]+/[A-Za-z0-9._-]+@' "${CORE_WF[@]}" "${TMPL_WF[@]}")
if [ "$shape_seen" -eq 0 ]; then
  fail "no remote actions found in any workflow — this test is not testing anything"
elif [ "$shape_bad" -eq 0 ]; then
  pass "all ${shape_seen} remote-action pin(s) are full-SHA with a version comment"
fi

# action -> sha, e.g. "actions/checkout 9c091bb...". Extracts the SHA, ignoring the comment.
pins() { grep -rhoE 'uses: *[A-Za-z0-9._-]+/[A-Za-z0-9._-]+@[0-9a-f]{40}' "$@" \
           | sed -E 's/uses: *//' | sort -u; }

echo "action pins: the core and the templates must agree on the SHA of every SHARED action"
core_pins="$(pins "${CORE_WF[@]}")"
tmpl_pins="$(pins "${TMPL_WF[@]}")"

if [ -z "$core_pins" ]; then fail "no SHA-pinned actions in the core workflows — this test is not testing anything"; fi
if [ -z "$tmpl_pins" ]; then fail "no SHA-pinned actions in the template workflows — this test is not testing anything"; fi

shared=0
while IFS= read -r cp; do
  action="${cp%@*}"; core_sha="${cp#*@}"
  # every SHA this action is pinned to across the templates
  tmpl_shas="$(grep -E "^${action}@" <<<"$tmpl_pins" | sed -E 's/.*@//' | sort -u || true)"
  [ -n "$tmpl_shas" ] || continue          # not used in the templates — nothing to keep in lockstep
  shared=$((shared + 1))
  bad=0
  while IFS= read -r ts; do
    [ "$ts" = "$core_sha" ] || { bad=1; fail "${action}: core is pinned to ${core_sha} but a template pins ${ts}. Dependabot bumped the core and cannot see templates/ — bump the template workflows to ${core_sha} too."; }
  done <<<"$tmpl_shas"
  [ "$bad" -eq 0 ] && pass "${action} is ${core_sha} in the core and in every template"
done <<<"$core_pins"

if [ "$shared" -eq 0 ]; then
  fail "no action is shared between the core and the templates — the lockstep check is vacuous. Did the workflows change shape?"
else
  pass "checked ${shared} action(s) shared between the core and the templates"
fi

# ---------------------------------------------------------------------------------------
# Every action must be pinned to an immutable ref. `@main` / `@master` / `@latest` is a moving
# target: the action can change under you between two runs of the same commit, which is the
# opposite of what a required status check is for.
echo "action pins: nothing may float on a branch ref"
if float="$(grep -rhoE 'uses: *[^ ]+@(main|master|latest)' "${CORE_WF[@]}" "${TMPL_WF[@]}" || true)"; [ -n "$float" ]; then
  fail "an action floats on a branch ref (it can change under you between runs): ${float}"
else
  pass "every action is pinned to a full SHA, none float on main/master/latest"
fi

finish
```

- [ ] **Step 2: Run the test against the still-tagged workflows to verify it goes RED**

Run: `bash template-tests/test_action_pins.sh; echo "exit=$?"`
Expected: FAIL — the shape check reports every bare tag, e.g. `FAIL not SHA-pinned with a version comment: .github/workflows/secret-scan.yml:18:      - uses: actions/checkout@v7`, and the run ends with `N FAILURE(S)` / `exit=1`. This proves the new assertion actually rejects the status quo.

- [ ] **Step 3: Convert the core-workflow pins (checkout) to SHA**

In each of the three files, replace `actions/checkout@v7` with the SHA pin. Exact edits:

`.github/workflows/secret-scan.yml` line 18:
```yaml
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
```
`.github/workflows/guard-base-branch.yml` line 27 (note this one is indented under a step, no `- ` on the `uses:`):
```yaml
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
```
`.github/workflows/template-tests.yml` line 29:
```yaml
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
```

- [ ] **Step 4: Convert the template-workflow pins to SHA**

`templates/python/.github/workflows/ci.yml` lines 27–28:
```yaml
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0
```
`templates/node/.github/workflows/ci.yml` lines 17–18:
```yaml
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0
```
`templates/next/.github/workflows/ci.yml` lines 20–21:
```yaml
      - uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0
```

- [ ] **Step 5: Verify no bare tags remain**

Run: `grep -rnE 'uses: *actions/[a-z-]+@v[0-9]' .github/workflows/ templates/*/.github/workflows/ || echo "clean: no tag pins remain"`
Expected: `clean: no tag pins remain`

- [ ] **Step 6: Run the test to verify it now passes GREEN**

Run: `bash template-tests/test_action_pins.sh; echo "exit=$?"`
Expected: PASS — includes `ok   all 9 remote-action pin(s) are full-SHA with a version comment`, `ok   actions/checkout is 9c091bb...` lockstep lines, `ok   every action is pinned to a full SHA, none float on main/master/latest`, and ends with `ALL PASS` / `exit=0`.

- [ ] **Step 7: Run the full template-tests suite to confirm nothing else regressed**

Run: `for t in template-tests/test_*.sh; do echo "== $t =="; bash "$t" || echo "FAILED: $t"; done`
Expected: every suite ends `ALL PASS`. (`test_apply_rulesets.sh` may print `SKIP` lines for org-access blocks when run without a real `gh` org login — that is expected and is not a failure; watch for `FAILED:` lines, of which there should be none.)

- [ ] **Step 8: Commit**

```bash
git add template-tests/test_action_pins.sh \
  .github/workflows/secret-scan.yml \
  .github/workflows/guard-base-branch.yml \
  .github/workflows/template-tests.yml \
  templates/python/.github/workflows/ci.yml \
  templates/node/.github/workflows/ci.yml \
  templates/next/.github/workflows/ci.yml
git commit -m "feat: SHA-pin GitHub Actions; re-key lockstep test onto the SHA

Pin checkout/setup-node/setup-python to full 40-hex commit SHAs with
# vX.Y.Z comments across core and template workflows, closing the mutable-tag
supply-chain vector (cf. tj-actions/changed-files 2025). Rewrite
test_action_pins.sh to assert full-SHA pins + version comments and lockstep on
the SHA; float-ref guard preserved. Hardening spec Item 3."
```

---

## Self-Review

**1. Spec coverage (Item 3 + its Testing bullet):**
- "rewrite test_action_pins.sh to assert SHA pins + version comments" → Step 1, shape check (`@[0-9a-f]{40} +# *v[0-9]`). ✓
- "in lockstep across core and templates" → Step 1, lockstep check re-keyed onto `core_sha`/`tmpl_shas`. ✓
- "keep the float-ref guard" → Step 1, unchanged float check. ✓
- "SHA pins (7+ hex, with the version comment)" — decision resolved to full 40-hex (Dependabot-native). ✓
- Convert all pins across "all core and template workflows in lockstep" → Steps 3–4 cover all 9 occurrences in 6 files. ✓
- Dependabot "does bump SHA-pinned actions (updating both SHA and comment)" → no config change needed; comment format matches Dependabot output. ✓ (noted in File Structure)

**2. Placeholder scan:** No TBD/TODO/"handle edge cases". Every edit shows the literal line; every command shows expected output. ✓

**3. Type/name consistency:** `pins()` returns `action@sha`; consumers split on `@` into `action`/`core_sha` and compare against `tmpl_shas` — consistent throughout. The three SHAs in the resolved-values table match those in Steps 3–4 and the commit message verbatim. ✓
