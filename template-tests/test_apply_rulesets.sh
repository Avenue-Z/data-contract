#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=template-tests/lib.sh disable=SC1091
source template-tests/lib.sh

# This block drives the REAL gh against the REAL org: apply-rulesets.sh reads the org plan before
# it does anything, and every decision below hangs off it. A CI runner's GITHUB_TOKEN is
# repo-scoped and cannot read org details, so skip there rather than fail a run for a reason that
# has nothing to do with the change under test. The stub-driven cases further down cover the same
# decision logic without the network; this one exists to prove it works against the real API.
echo "apply-rulesets: honest reporting (needs live org access)"
if ! have_org_access; then
  skip "no authenticated access to the Avenue-Z org (expected on a CI runner) — the live-gh checks below are NOT running"
  skip "  the stub-driven cases further down still cover the same decision logic"
else
  if out=$(./scripts/apply-rulesets.sh --dry-run 2>&1); then
    pass "--dry-run exits 0"
  else
    fail "--dry-run should exit 0 even when protection is impossible"
  fi
  assert_match "explains what it did or skipped" 'free|skip|cannot|unavailable|would apply' "$out"

  echo "apply-rulesets: anti-brick — no ci.yml in template core means 'ci' must never be required"
  if [ -f .github/workflows/ci.yml ]; then
    fail "template core unexpectedly has ci.yml — this test's premise no longer holds, update it"
  else
    pass "confirmed no ci.yml present (test precondition for the anti-brick case)"
  fi
  assert_nomatch "'ci' is NOT listed as a required status check" 'required: ci$' "$out"
  assert_match   "'guard-base-branch' is listed as required" 'required: guard-base-branch' "$out"
  assert_match   "'secret-scan' is listed as required" 'required: secret-scan' "$out"
  # The MIRROR of the anti-brick case: the template DOES carry template-tests.yml, so the file-gated
  # add_context MUST inject 'template-tests' here. Asserting the injection (not just its absence when
  # the workflow is gone) is the behavioral coverage the file-gating condition otherwise lacked — a
  # regression that required it unconditionally would hang every PR in a generated repo pending forever.
  assert_match   "'template-tests' IS listed as required (its workflow is present in the template)" 'required: template-tests' "$out"
fi

# ---------------------------------------------------------------------------------------
# --org IS GONE FROM THIS SCRIPT, AND MUST STAY GONE.
#
# The org-wide apply used to live here behind `--org` — one flag away from the command you run on
# every new repo. That adjacency WAS the vulnerability: a fat-finger, a stray tab-complete, or an
# Up-arrow through shell history was all that separated "protect my repo" from "rewrite protection
# on all ~64 repos in Avenue-Z". It now lives in scripts/apply-org-ruleset.sh.
#
# These assertions exist so nobody re-adds the flag here for convenience. Convenience is exactly
# what we removed.
echo "apply-rulesets: --org must NOT be reachable from this script"
if out_org=$(./scripts/apply-rulesets.sh --org --dry-run 2>&1); then
  fail "--org still works on apply-rulesets.sh — the org-wide apply must not be one flag away from the routine command"
else
  pass "--org is refused by apply-rulesets.sh"
fi
assert_match "points the operator at the separate org script" 'apply-org-ruleset\.sh' "$out_org"
assert_nomatch "does not apply anything" 'created new org ruleset|updated existing org ruleset' "$out_org"

echo "apply-rulesets: --yes must NOT exist here either"
if out_yes=$(./scripts/apply-rulesets.sh --yes --dry-run 2>&1); then
  fail "--yes is still accepted — it is a consent bypass and must not exist"
else
  pass "--yes is refused by apply-rulesets.sh"
fi

# The script must not even CONTAIN the org-apply code any more. A flag guard that sits in front of
# a still-present POST to orgs/<org>/rulesets is one edit away from being reachable again.
echo "apply-rulesets: the org-apply code must be ABSENT, not merely guarded"
src="$(cat scripts/apply-rulesets.sh)"
assert_nomatch "no POST to orgs/<org>/rulesets anywhere in this script" 'orgs/\$\{ORG\}/rulesets' "$src"
assert_nomatch "no ~ALL / org-repo enumeration left behind" 'orgs/\$\{ORG\}/repos' "$src"

# ---------------------------------------------------------------------------------------
# CRITERION 6 — the private + Free path must be HONEST.
#
# Every run above exits early at "cannot determine target repo" (this working copy has no
# GitHub remote), so NOTHING above ever reaches the private+Free branch. That branch is the
# whole point of the script: on Free, branch protection does not exist for private repos,
# and the script must say so — "main is NOT protected, a direct push WILL succeed" — instead
# of claiming success. To actually drive it, put a fake `gh` on PATH that answers `free` for
# the plan and `PRIVATE` for the visibility. Without this, replacing the entire warning block
# with `info "protection applied."` — a script that LIES — still passed the suite.
echo "apply-rulesets: criterion 6 — private repo + Free plan reports the truth"
STUB="$(mktemp -d)"
trap 'rm -rf "${STUB}"' EXIT
cat > "${STUB}/gh" <<'STUBEOF'
#!/usr/bin/env bash
# Minimal fake gh: a private repo in an org on the Free plan.
case "$*" in
  *"orgs/Avenue-Z"*)  echo free ;;
  *nameWithOwner*)    echo "Avenue-Z/fake-private-repo" ;;
  *visibility*)       echo "PRIVATE" ;;
  *) echo "fake gh: unexpected call: gh $*" >&2; exit 1 ;;
esac
STUBEOF
chmod +x "${STUB}/gh"

if out_priv=$(PATH="${STUB}:${PATH}" ./scripts/apply-rulesets.sh --dry-run 2>&1); then
  pass "private+Free exits 0 (a plan limit is an honest report, not an error)"
else
  fail "private+Free should exit 0, got non-zero. Output: ${out_priv}"
fi
assert_match   "says main/staging/dev are NOT protected" 'not protected' "$out_priv"
assert_match   "says a direct push to main will succeed" 'direct push to main will succeed' "$out_priv"
assert_nomatch "makes no false claim of applied protection" 'ruleset applied|protection applied|now protected' "$out_priv"

# ---------------------------------------------------------------------------------------
# IDEMPOTENCY — GitHub allows multiple rulesets with the same name. A plain unconditional
# POST every run would create a duplicate instead of updating the one already in force.
# These cases drive a repo that IS reachable (PUBLIC, so the Free-plan honesty exit above
# is never hit) and vary what the rulesets-list GET returns.
echo "apply-rulesets: idempotency — existing ruleset with matching name triggers update (PUT), not a duplicate create"
cat > "${STUB}/gh" <<'STUBEOF'
#!/usr/bin/env bash
case "$*" in
  *"orgs/Avenue-Z"*)                          echo team ;;
  *nameWithOwner*)                            echo "Avenue-Z/repo-template" ;;
  *visibility*)                               echo "PUBLIC" ;;
  *"repos/Avenue-Z/repo-template/rulesets"*)  echo '[{"id":18889104,"name":"avenue-z-branch-protection"}]' ;;
  *) echo "fake gh: unexpected call: gh $*" >&2; exit 1 ;;
esac
STUBEOF
chmod +x "${STUB}/gh"

if out_update=$(PATH="${STUB}:${PATH}" ./scripts/apply-rulesets.sh --dry-run 2>&1); then
  pass "existing-ruleset dry-run exits 0"
else
  fail "existing-ruleset dry-run should exit 0. Output: ${out_update}"
fi
assert_match   "says it would PUT/update the existing ruleset" 'put|update' "$out_update"
assert_match   "names the existing ruleset id 18889104" '18889104' "$out_update"
assert_nomatch "does not say it would POST/create a new ruleset" 'would post|create new' "$out_update"

echo "apply-rulesets: idempotency — no existing ruleset with matching name triggers create (POST)"
cat > "${STUB}/gh" <<'STUBEOF'
#!/usr/bin/env bash
case "$*" in
  *"orgs/Avenue-Z"*)                          echo team ;;
  *nameWithOwner*)                            echo "Avenue-Z/repo-template" ;;
  *visibility*)                               echo "PUBLIC" ;;
  *"repos/Avenue-Z/repo-template/rulesets"*)  echo '[]' ;;
  *) echo "fake gh: unexpected call: gh $*" >&2; exit 1 ;;
esac
STUBEOF
chmod +x "${STUB}/gh"

if out_create=$(PATH="${STUB}:${PATH}" ./scripts/apply-rulesets.sh --dry-run 2>&1); then
  pass "no-existing-ruleset dry-run exits 0"
else
  fail "no-existing-ruleset dry-run should exit 0. Output: ${out_create}"
fi
assert_match   "says it would POST/create a new ruleset" 'would post|create new' "$out_create"
assert_nomatch "does not say it would PUT/update an existing ruleset" 'would put|update existing' "$out_create"

echo "apply-rulesets: idempotency — a failed ruleset-list lookup must die, not silently create a duplicate"
cat > "${STUB}/gh" <<'STUBEOF'
#!/usr/bin/env bash
case "$*" in
  *"orgs/Avenue-Z"*)                          echo team ;;
  *nameWithOwner*)                            echo "Avenue-Z/repo-template" ;;
  *visibility*)                               echo "PUBLIC" ;;
  *"repos/Avenue-Z/repo-template/rulesets"*)  echo "HTTP 403: Forbidden (rate limited)" >&2; exit 1 ;;
  *) echo "fake gh: unexpected call: gh $*" >&2; exit 1 ;;
esac
STUBEOF
chmod +x "${STUB}/gh"

if out_fail=$(PATH="${STUB}:${PATH}" ./scripts/apply-rulesets.sh --dry-run 2>&1); then
  fail "a failed ruleset lookup should NOT exit 0 — it must die rather than guess. Output: ${out_fail}"
else
  pass "a failed ruleset lookup makes the script die (non-zero exit)"
fi
assert_match   "explains the lookup failure" 'cannot list existing rulesets' "$out_fail"
assert_nomatch "never falls through to claiming it would create/POST a duplicate" 'would post|create new' "$out_fail"

finish
