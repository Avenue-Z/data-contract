#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=template-tests/lib.sh disable=SC1091
source template-tests/lib.sh

REPO_RULESET=.github/rulesets/repo-ruleset.json
ORG_RULESET=.github/rulesets/org-ruleset.json

echo "rulesets: valid JSON"
if jq empty "$REPO_RULESET" >/dev/null 2>&1; then pass "$REPO_RULESET is valid JSON"; else fail "$REPO_RULESET is valid JSON"; fi
if jq empty "$ORG_RULESET" >/dev/null 2>&1; then pass "$ORG_RULESET is valid JSON"; else fail "$ORG_RULESET is valid JSON"; fi

# `template-tests` must never be BAKED INTO repo-ruleset.json. That file is shared by the template
# AND every repo generated from it — and a generated repo has no template-tests workflow, because
# init-repo.sh deletes it. Baking the context in would make every generated repo require a check
# that can never report: PRs hang PENDING FOREVER and the repo is unmergeable from day one.
# It is INJECTED by apply-rulesets.sh, and only when the workflow file is actually present.
echo "rulesets: 'template-tests' must never be a baked-in required context (generated repos have no such workflow)"
if grep -q '"context": *"template-tests"' .github/rulesets/*.json; then
  fail "'template-tests' is hard-coded in a ruleset — every generated repo would hang every PR pending forever"
else
  pass "'template-tests' is absent from the committed rulesets (apply-rulesets.sh injects it only when the workflow exists)"
fi

echo "rulesets: 'ci' must never be a required context (core has no ci workflow -> pending forever)"
if grep -q '"context": *"ci"' .github/rulesets/*.json; then
  fail "'ci' context found in rulesets (would hang pending forever)"
else
  pass "'ci' context absent from rulesets"
fi

echo "rulesets: required_approving_review_count must be 0 (solo maintainer cannot self-approve)"
for f in "$REPO_RULESET" "$ORG_RULESET"; do
  count=$(jq -r '.rules[] | select(.type=="pull_request") | .parameters.required_approving_review_count' "$f")
  assert_eq "0" "$count" "$f required_approving_review_count is 0"
done

# ---------------------------------------------------------------------------------------
# REVIEW ENFORCEMENT MUST BE INTERNALLY CONSISTENT — AND MUST MATCH WHAT SECURITY.md CLAIMS.
#
# `require_code_owner_review: true` with `required_approving_review_count: 0` is the trap: it
# READS like enforced code-owner review while requiring no approval at all. That mismatch is how
# SECURITY.md came to claim CODEOWNERS "forces a human to review a change to the guard" when the
# shipped config forced nothing — the exact enforcement theater this repo exists to avoid.
#
# So the two flags move TOGETHER, or the suite fails:
#   count 0   + code-owner review off  -> review is NOT enforced. The current, deliberate choice
#                                         (solo maintainer). SECURITY.md documents it as an
#                                         ACCEPTED RISK, and must keep saying so.
#   count >=1 + code-owner review on   -> review IS enforced. Legitimate, but it means every PR
#                                         needs a second human. If you switch to this, REWRITE the
#                                         SECURITY.md section — it currently tells the reader they
#                                         are NOT protected.
echo "rulesets: review enforcement must be internally consistent (no 'looks enforced, isn't' config)"
for f in "$REPO_RULESET" "$ORG_RULESET"; do
  count=$(jq -r '.rules[] | select(.type=="pull_request") | .parameters.required_approving_review_count' "$f")
  owner=$(jq -r '.rules[] | select(.type=="pull_request") | .parameters.require_code_owner_review' "$f")
  if [ "$count" = "0" ] && [ "$owner" = "false" ]; then
    pass "$f: review not enforced, and does not pretend to be (count 0, code-owner review off)"
  elif [ "$count" -ge 1 ] 2>/dev/null && [ "$owner" = "true" ]; then
    pass "$f: review genuinely enforced (count $count, code-owner review on)"
  else
    fail "$f: count=$count with require_code_owner_review=$owner is enforcement theater — code-owner review with 0 required approvals requires nobody. Set both or neither, and update SECURITY.md to match."
  fi
done

# SECURITY.md must not go back to claiming CODEOWNERS is a control while the ruleset says it is
# not. This is a doc assertion because the lie lived in the doc, not in the JSON.
echo "rulesets: SECURITY.md must state honestly that review is not enforced"
repo_owner=$(jq -r '.rules[] | select(.type=="pull_request") | .parameters.require_code_owner_review' "$REPO_RULESET")
repo_count=$(jq -r '.rules[] | select(.type=="pull_request") | .parameters.required_approving_review_count' "$REPO_RULESET")
sec="$(cat SECURITY.md)"
if [ "$repo_owner" = "false" ] && [ "$repo_count" = "0" ]; then
  assert_match "SECURITY.md says CODEOWNERS forces nothing" 'CODEOWNERS.{0,20}forces nothing' "$sec"
  assert_nomatch "SECURITY.md does not claim CODEOWNERS forces a review" 'is the thing that forces a human to review' "$sec"
fi

# ---------------------------------------------------------------------------------------
# THE ORG RULESET MUST NOT REQUIRE STATUS CHECKS. It targets repository_name ~ALL — every
# repo in Avenue-Z, ~64 of them, of which none was generated from this template and none has
# guard-base-branch.yml or secret-scan.yml. A required check that never reports does not fail
# a PR; it hangs it PENDING FOREVER. With enforcement:active and bypass_actors:[], one
# `apply-org-ruleset.sh` would take push AND merge away from every repo in the org at once.
#
# This is the assertion that keeps that landmine from being re-laid. Required checks are
# per-repo (repo-ruleset.json), applied only to repos that ship the workflows.
echo "rulesets: the ORG ruleset must declare NO required_status_checks (~ALL includes ~64 repos with no CI)"
org_checks=$(jq -r '[.rules[] | select(.type=="required_status_checks")] | length' "$ORG_RULESET")
assert_eq "0" "$org_checks" "$ORG_RULESET has zero required_status_checks rules"
org_target=$(jq -r '.conditions.repository_name.include | join(",")' "$ORG_RULESET")
if [ "$org_target" = "~ALL" ] && [ "$org_checks" != "0" ]; then
  fail "$ORG_RULESET targets ~ALL repos AND requires status checks — every repo without those workflows becomes permanently unmergeable"
else
  pass "$ORG_RULESET does not combine a ~ALL target with required status checks"
fi

echo "rulesets: required status check contexts match real workflow job keys"
contexts=$(jq -r '.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context' "$REPO_RULESET" | sort)
expected=$(printf 'guard-base-branch\nsca\nsecret-scan')
assert_eq "$expected" "$contexts" "$REPO_RULESET required contexts == {guard-base-branch, sca, secret-scan}"

# ---------------------------------------------------------------------------------------
# THE THREE FIELDS THAT SILENTLY DEFANG A RULESET. Each of these was, at some point in this
# repo's history, wrong — and the whole suite stayed green:
#
#   bypass_actors: [{"actor_type":"OrganizationAdmin","bypass_mode":"always"}]
#       -> verified live: enforcement reads "active" while an org owner pushes straight to
#          main. A ruleset that exempts exactly the people most likely to push to main
#          protects nothing. It must be EMPTY.
#   enforcement: "evaluate"
#       -> GitHub reports what WOULD have happened and blocks nothing. Looks identical in
#          the API response except for one word.
#   ref_name.include missing dev/staging
#       -> main stays protected, the two branches everyone actually works on do not.
echo "rulesets: bypass_actors must be EMPTY (an org-admin bypass makes 'enforcement: active' a lie)"
for f in "$REPO_RULESET" "$ORG_RULESET"; do
  n=$(jq -r '.bypass_actors | length' "$f")
  assert_eq "0" "$n" "$f bypass_actors is []"
done

echo "rulesets: enforcement must be 'active' ('evaluate' reports violations and blocks nothing)"
for f in "$REPO_RULESET" "$ORG_RULESET"; do
  assert_eq "active" "$(jq -r '.enforcement' "$f")" "$f enforcement is active"
done

echo "rulesets: ref_name.include must cover main, staging AND dev"
want_refs=$(printf 'refs/heads/main\nrefs/heads/staging\nrefs/heads/dev')
for f in "$REPO_RULESET" "$ORG_RULESET"; do
  got_refs=$(jq -r '.conditions.ref_name.include[]' "$f")
  assert_eq "$want_refs" "$got_refs" "$f protects exactly main, staging, dev"
done

echo "rulesets: deletion and non_fast_forward rules must both be present"
for f in "$REPO_RULESET" "$ORG_RULESET"; do
  for rule in deletion non_fast_forward; do
    n=$(jq -r --arg r "$rule" '[.rules[] | select(.type==$r)] | length' "$f")
    assert_eq "1" "$n" "$f declares the '$rule' rule"
  done
done

# ---------------------------------------------------------------------------------------
# REQUIRED CONTEXT REACHABILITY.
#
# A required status check that never reports does NOT fail a PR — it hangs PENDING
# FOREVER and nothing can ever be merged. The two ways to never report:
#   1. no job of that name exists at all;
#   2. a job of that name exists but is a MATRIX job — GitHub names those contexts
#      "job (leg)", so a context named plainly "job" never appears.
# This repo already asserted (1) for guard-base-branch by hand. Below, both are asserted
# for EVERY required context, in the core rulesets and in the 'ci' context that
# apply-rulesets.sh injects into every generated stack repo.
context_reachable() { # <workflow-dir> <context>  -> exit 0 and print why, or exit 1 and print why not
  python3 - "$1" "$2" <<'PY'
import glob, os, sys, yaml

wdir, ctx = sys.argv[1], sys.argv[2]
matrix_hits = []
for wf in sorted(glob.glob(os.path.join(wdir, "*.yml")) + glob.glob(os.path.join(wdir, "*.yaml"))):
    with open(wf) as fh:
        doc = yaml.safe_load(fh) or {}
    job = (doc.get("jobs") or {}).get(ctx)
    if job is None:
        continue
    if (job.get("strategy") or {}).get("matrix"):
        matrix_hits.append(wf)
        continue
    print(f"reachable: {wf} declares a non-matrix job '{ctx}'")
    sys.exit(0)

if matrix_hits:
    print(f"UNREACHABLE: {matrix_hits[0]} declares '{ctx}' as a MATRIX job. GitHub names its "
          f"contexts '{ctx} (<leg>)' — a context named plainly '{ctx}' NEVER reports, so every "
          f"PR hangs pending forever. Add a non-matrix aggregate job named exactly '{ctx}' that "
          f"`needs` the matrix and runs with `if: always()`.")
else:
    jobs = []
    for wf in sorted(glob.glob(os.path.join(wdir, "*.yml")) + glob.glob(os.path.join(wdir, "*.yaml"))):
        with open(wf) as fh:
            doc = yaml.safe_load(fh) or {}
        jobs += list((doc.get("jobs") or {}).keys())
    print(f"UNREACHABLE: no job named '{ctx}' in {wdir} (jobs found: {sorted(jobs)}). A required "
          f"context that never reports hangs every PR pending forever.")
sys.exit(1)
PY
}

# Both files are still swept: if a required check is ever re-added to the org ruleset, the
# assertion above fails AND this one holds it to the same reachability bar.
echo "rulesets: every required context resolves to a REACHABLE (existing, non-matrix) job"
for f in "$REPO_RULESET" "$ORG_RULESET"; do
  for ctx in $(jq -r '.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context' "$f"); do
    if out=$(context_reachable .github/workflows "$ctx" 2>&1); then
      pass "$f: context '$ctx' — $out"
    else
      fail "$f: context '$ctx' — $out"
    fi
  done
done

echo "workflows: the 'ci' context apply-rulesets.sh injects must be reachable in EVERY stack template"
# Tie the premise to the script: apply-rulesets.sh appends {"context":"ci"} to the required
# checks whenever .github/workflows/ci.yml exists. Every stack template ships one, so every
# generated repo gets a required 'ci' — which must therefore be a real, non-matrix job.
# Both required contexts are FILE-GATED: apply-rulesets.sh adds them only when the workflow that
# reports them actually exists. That is what lets one shared repo-ruleset.json serve both the
# template (which has template-tests.yml but no ci.yml) and a generated repo (the reverse) without
# either one requiring a check that can never report.
if grep -qE 'add_context +ci +\.github/workflows/ci\.yml' scripts/apply-rulesets.sh; then
  pass "apply-rulesets.sh injects 'ci' only when ci.yml exists (premise for the checks below)"
else
  fail "apply-rulesets.sh no longer file-gates the 'ci' context — this test's premise changed, update it"
fi
if grep -qE 'add_context +template-tests +\.github/workflows/template-tests\.yml' scripts/apply-rulesets.sh; then
  pass "apply-rulesets.sh injects 'template-tests' only when that workflow exists"
else
  fail "apply-rulesets.sh must file-gate 'template-tests' — a generated repo has no such workflow, and an unconditional context would hang every PR pending forever"
fi
for tdir in templates/*/; do
  stack="$(basename "$tdir")"
  wdir="${tdir}.github/workflows"
  if [ ! -f "${wdir}/ci.yml" ]; then
    fail "templates/${stack} has no .github/workflows/ci.yml"
    continue
  fi
  if out=$(context_reachable "$wdir" ci 2>&1); then
    pass "templates/${stack}: required context 'ci' — $out"
  else
    fail "templates/${stack}: required context 'ci' — $out"
  fi
done

finish
