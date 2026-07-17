#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=template-tests/lib.sh disable=SC1091
source template-tests/lib.sh

T=templates/next
CI=$T/.github/workflows/ci.yml
VJ=$T/vercel.json

echo "next stack: the skeleton exists"
assert_file "package.json"      "$T/package.json"
assert_file "package-lock.json (npm ci needs it — a template that cannot 'npm ci' has no reproducible CI)" "$T/package-lock.json"
assert_file "tsconfig.json"     "$T/tsconfig.json"
assert_file "next.config.mjs"   "$T/next.config.mjs"
assert_file "eslint.config.mjs" "$T/eslint.config.mjs"
assert_file "app router layout" "$T/src/app/layout.tsx"
assert_file "app router page"   "$T/src/app/page.tsx"
assert_file "a test exists"     "$T/tests/smoke.test.ts"
assert_file "ci.yml"            "$CI"
assert_file "vercel.json"       "$VJ"

# ---------------------------------------------------------------------------------------
# THE RULESET CONTRACT. apply-rulesets.sh requires the status-check context "ci" once ci.yml
# exists. A required check that never reports does NOT fail a PR — it hangs it PENDING FOREVER
# and the repo becomes unmergeable. So the job key must be LITERALLY `ci`, not `build`, not a
# matrix (a matrix leg is named "ci (20)", and a bare "ci" context would never exist).
echo "next stack: the ci job must be named exactly 'ci' and must not be a matrix"
# Match the job key anywhere at top-level job indent, not just the line immediately after `jobs:`.
# The old `grep -A1 '^jobs:' | tail -1` assumed no comment sits between `jobs:` and the key — a
# comment there (the style used throughout this repo) would false-fail a correct workflow.
if grep -qE '^  ci:$' "$CI"; then
  pass "jobs key is literally 'ci'"
else
  fail "the job key must be literally 'ci' — the ruleset requires that exact context"
fi
ci_src="$(cat "$CI")"
assert_nomatch "the ci job is NOT a matrix (a matrix leg is named 'ci (x)', so context 'ci' would never report)" 'strategy:' "$ci_src"
assert_match   "declares a read-only permissions block" 'contents: *read' "$ci_src"

echo "next stack: CI must actually BUILD, not just typecheck"
# A Next app that type-checks clean can still fail `next build` — a bad route export, a
# server/client boundary violation, a missing build-time env var. Vercel runs this build on every
# deploy, so CI must run it too; otherwise the first place a broken build surfaces is the deploy.
assert_match "runs npm ci"        'npm ci' "$ci_src"
assert_match "runs lint"          'npm run lint' "$ci_src"
assert_match "runs typecheck"     'npm run typecheck' "$ci_src"
assert_match "runs the tests"     'npm test' "$ci_src"
assert_match "runs the BUILD"     'npm run build' "$ci_src"

echo "next stack: package.json wires the scripts CI calls"
for s in build lint typecheck test; do
  if jq -e --arg s "$s" '.scripts[$s]' "$T/package.json" >/dev/null 2>&1; then
    pass "package.json defines the '$s' script"
  else
    fail "package.json has no '$s' script, but ci.yml calls it"
  fi
done

# ---------------------------------------------------------------------------------------
# DEPLOYS SHIP OFF. This is the control, and it is easy to get backwards: Vercel treats every
# UNSPECIFIED branch as DEPLOYABLE. So `deploymentEnabled: false` is not a stylistic default —
# it is the only posture under which linking a project does not immediately start deploying.
echo "next stack: vercel.json must ship with deploys DISABLED"
assert_ok "vercel.json is valid JSON" jq empty "$VJ"
enabled="$(jq -r '.git.deploymentEnabled' "$VJ")"
assert_eq "false" "$enabled" "vercel.json sets git.deploymentEnabled = false"
if [ "$enabled" = "true" ]; then
  fail "deploymentEnabled is TRUE — linking this project would start deploying every branch immediately"
fi

# ---------------------------------------------------------------------------------------
echo "next stack: init-repo.sh accepts 'next' and treats it as an npm project"
init="$(cat scripts/init-repo.sh)"
assert_match "the stack case accepts next" 'python\|node\|next' "$init"
assert_match "usage advertises next" 'python\|node\|next' "$init"
assert_match "next maps to the npm dependabot ecosystem" 'node\|next\) *eco=npm' "$init"

# init-repo must REFUSE to continue if vercel.json did not make it across: a missing vercel.json
# does not mean "no Vercel config", it means EVERY BRANCH DEPLOYS.
assert_match "init-repo dies if vercel.json is missing after the copy" 'copy failed: vercel.json missing' "$init"
assert_match "init-repo dies if vercel.json does not disable deploys" 'does not disable deployments' "$init"

echo "next stack: a bogus stack is still rejected"
if out=$(./scripts/init-repo.sh nextjs --no-push 2>&1); then
  fail "'nextjs' was accepted — only python|node|next are valid"
else
  pass "an unknown stack ('nextjs') is rejected"
fi
assert_match "names the valid stacks" "'python', 'node' or 'next'" "$out"

finish
