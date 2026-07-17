#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "${REPO_ROOT}/template-tests/lib.sh"

# Build a throwaway clone so we never mutate the real template.
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
git clone -q "${REPO_ROOT}" "${WORK}/repo"
cd "${WORK}/repo"
git checkout -qb dev 2>/dev/null || git checkout -q dev

echo "init-repo: python"
./scripts/init-repo.sh python --no-push

# Criterion 15 — no head carries templates/
assert_no_dir "templates/ removed from working tree" templates
for b in dev staging main; do
  if git ls-tree -r --name-only "$b" | grep -q '^templates/'; then
    fail "branch $b still contains templates/"
  else
    pass "branch $b is free of templates/"
  fi
done

# Criterion 3 — all three branches exist
for b in dev staging main; do
  assert_ok "branch $b exists" git show-ref --verify --quiet "refs/heads/$b"
done

# ZERO DEAD FILES. A generated repo must not ship the template's own self-tests (two of which
# INVERT once ci.yml exists — they assert the core has none — and would fail out of the box),
# nor the template's own 500-line spec/plan. Assert on the working tree AND on every branch,
# because a head that still carries them is the same dead weight one commit away.
assert_no_dir  "template-tests/ removed from working tree" template-tests
# The template's OWN design docs live in template-docs/ (not docs/superpowers/{specs,plans}/, so a
# spec the adopter already wrote is never deleted). init-repo removes the whole dir wholesale.
assert_no_dir  "template-docs/ removed from working tree" template-docs
assert_no_file "the template's own test_sca.sh did not ship (it lives in template-tests/)" template-tests/test_sca.sh
# The WORKFLOW that runs that suite must go too. If it stayed, a generated repo would ship a job
# that runs a directory init-repo just deleted — and the moment anyone added `template-tests` to
# that repo's required checks, it would never report and hang every PR PENDING FOREVER.
assert_no_file "template-tests.yml workflow removed (it runs a suite that no longer exists here)" .github/workflows/template-tests.yml
# The workflows a generated repo SHOULD keep must survive the cull.
assert_file    "guard-base-branch.yml survived" .github/workflows/guard-base-branch.yml
assert_file    "secret-scan.yml survived" .github/workflows/secret-scan.yml
assert_file    "sca.yml survived (core workflow, ships into generated repos)" .github/workflows/sca.yml
assert_file    "sca-policy.json survived" .github/sca-policy.json
assert_file    "sca-gate.sh survived" scripts/sca-gate.sh
# Same class as the SCA scripts above: the generated python repo's required `ci` check runs both of
# these (bandit job + ci aggregate gate). If a future init-repo.sh ever dropped or relocated scripts/,
# every generated python repo's `ci` check would fail with a missing-file error and no test would catch
# it. Guard their survival the same way sca-gate.sh is guarded.
assert_file    "bandit-gate.sh survived (python ci bandit job depends on it)" scripts/bandit-gate.sh
assert_file    "ci-aggregate-gate.sh survived (python ci gate depends on it)" scripts/ci-aggregate-gate.sh
# The generated repo's specs/ and plans/ must carry nothing but their README. This ALSO guards the
# template's own convention: a template design doc misplaced into docs/superpowers/specs/ (where the
# superpowers skills write by default) instead of template-docs/ would survive init and ship into
# every generated repo. Catching a stray dated doc here turns that silent rot into a red test.
# By pattern, not by filename: a spec added tomorrow must not slip through the way 2026-07-14 once
# did when this asserted only the 2026-07-13 files by name. Nothing but a README may remain.
leftover_docs="$(find docs/superpowers/specs docs/superpowers/plans -maxdepth 1 -type f -name '*.md' ! -name 'README.md')"
if [ -z "${leftover_docs}" ]; then
  pass "no design docs survived in specs/ or plans/ (template docs belong in template-docs/)"
else
  fail "design docs survived in specs/ or plans/ — a template doc misplaced outside template-docs/? ${leftover_docs}"
fi

# The front door is template-only. The seed (README.repo.tmpl) must have been swapped IN as
# README.md, and neither the seed file nor the adoption playbook may survive into the generated repo.
# A generated README carrying the template's front-door title inherited the exact cruft the swap exists
# to prevent — so assert it IS the skeleton, not just that the tmpl is gone.
assert_no_file "seed README.repo.tmpl removed" README.repo.tmpl
assert_no_file "adoption playbook docs/ADOPTION.md removed" docs/ADOPTION.md
assert_file    "README.md present (the seed, swapped in)" README.md
assert_match   "generated README is the seed skeleton" 'TODO: repo-name' "$(cat README.md)"
assert_nomatch "generated README is NOT the template front door" 'Avenue-Z Repo Template' "$(cat README.md)"

for b in dev staging main; do
  if git ls-tree -r --name-only "$b" | grep -qE '^\.github/workflows/template-tests\.yml$'; then
    fail "branch $b still carries .github/workflows/template-tests.yml"
  else
    pass "branch $b is free of the template-tests workflow"
  fi
  if git ls-tree -r --name-only "$b" | grep -qE '^template-tests/|^template-docs/|^docs/superpowers/(specs|plans)/20[0-9][0-9]-'; then
    fail "branch $b still carries the template's self-tests or its own spec/plan"
  else
    pass "branch $b is free of the template's self-tests and its own spec/plan"
  fi
  if git ls-tree -r --name-only "$b" | grep -qE '^README\.repo\.tmpl$|^docs/ADOPTION\.md$'; then
    fail "branch $b still carries the template's front-door files (README.repo.tmpl / docs/ADOPTION.md)"
  else
    pass "branch $b is free of the template's front-door files"
  fi
done

# The stack's OWN tests/ skeleton must SURVIVE — the point of template-tests/ is that removing
# the template's suite does not take the generated repo's test directory with it.
assert_file "the python skeleton's tests/ survived" tests/test_smoke.py
assert_file "the python skeleton's conftest.py survived" tests/conftest.py

# Criterion 1 — the python skeleton is real
assert_file "pyproject.toml copied" pyproject.toml
assert_file "ci.yml copied" .github/workflows/ci.yml

# Criterion 8 — no --team means no inert CODEOWNERS
assert_no_file "no CODEOWNERS without --team" .github/CODEOWNERS
assert_no_file "CODEOWNERS.tmpl removed" .github/CODEOWNERS.tmpl

# Criterion 7 — re-run is a no-op, exit 0
if ./scripts/init-repo.sh python --no-push; then pass "re-run exits 0"; else fail "re-run failed"; fi

# Criterion 11 — a bogus team WARNS and exits 0; it does not set -e crash
cd "${WORK}" && rm -rf repo2 && git clone -q "${REPO_ROOT}" repo2 && cd repo2
git checkout -qb dev 2>/dev/null || git checkout -q dev
if out=$(./scripts/init-repo.sh python --team definitely-not-a-real-team --no-push 2>&1); then
  pass "bogus --team exits 0 (guarded, not fatal)"
  assert_match "warned about the missing team" 'does not exist' "$out"
  assert_no_file "no CODEOWNERS written for a bogus team" .github/CODEOWNERS
else
  fail "bogus --team crashed instead of warning (set -e trap)"
fi

# Criterion 11 (the other half) — "I could not verify" is NOT "verified absent".
#
# THE PROJECT'S #1 INVARIANT. A 404 is an ANSWER (team absent -> warn, drop CODEOWNERS,
# exit 0). Anything else — expired auth, network, rate limit — is NOT an answer, and the
# script must DIE rather than silently downgrade the repo to no code-owner review. A bare
# `if ! gh api ...` treats a 401 exactly like a 404; that is the failure this test exists
# to catch. An invalid GH_TOKEN gives a real 401 from the real API, so this exercises the
# actual guard, not a mock of it.
cd "${WORK}" && rm -rf repo3 && git clone -q "${REPO_ROOT}" repo3 && cd repo3
git checkout -qb dev 2>/dev/null || git checkout -q dev
if out=$(GH_TOKEN=invalid_token_xyz ./scripts/init-repo.sh python --team automation --no-push 2>&1); then
  fail "unverifiable team (bad auth) exited 0 — a 401 was silently treated as 'team absent'"
else
  pass "unverifiable team (bad auth) exits non-zero"
fi
assert_match  "said it cannot verify the team" 'cannot verify' "$out"
assert_no_file "no CODEOWNERS written when the team could not be verified" .github/CODEOWNERS
assert_file    "CODEOWNERS.tmpl preserved (nothing dropped on an unverifiable answer)" .github/CODEOWNERS.tmpl

# Minor — `--team --no-push` must not set TEAM='--no-push'
cd "${WORK}/repo3"
if ./scripts/init-repo.sh python --team --no-push >/dev/null 2>&1; then
  fail "--team consumed the next flag as a slug"
else
  pass "--team rejects a value that begins with '-'"
fi

# ---------------------------------------------------------------------------------------
# NO GITHUB REMOTE = "I COULD NOT CHECK", NOT "IT'S FINE".
#
# These clones have a local-path origin, so `gh repo view` fails and there is no repo to check
# team write access against. The script used to collapse that (and an expired token, and a
# network blip) into repo="" and then write CODEOWNERS anyway — shipping the inert
# enforcement-theater file the whole feature exists to prevent, while the test said "ok".
#
# The honest behaviour: write the file, but say LOUDLY that write access is UNVERIFIED and the
# file may be inert. Drive it with a stub whose team lookup succeeds and whose `repo view` fails
# the way a missing GitHub remote actually fails.
echo "init-repo: no GitHub remote — CODEOWNERS is written but LOUDLY flagged as unverified"
STUB_NOREMOTE="$(mktemp -d)"
cat > "${STUB_NOREMOTE}/gh" <<'STUBEOF'
#!/usr/bin/env bash
case "$*" in
  *"repo view"*)
    echo "none of the git remotes configured for this repository point to a known GitHub host. To tell gh about a new GitHub host, please use \`gh auth login\`" >&2
    exit 1 ;;
  *"orgs/Avenue-Z/teams/automation"*)
    echo '{"slug":"automation"}' ;;
  *)
    echo "fake gh: unexpected call: gh $*" >&2; exit 1 ;;
esac
STUBEOF
chmod +x "${STUB_NOREMOTE}/gh"

cd "${WORK}" && rm -rf repo4 && git clone -q "${REPO_ROOT}" repo4 && cd repo4
git checkout -qb dev 2>/dev/null || git checkout -q dev
if out=$(PATH="${STUB_NOREMOTE}:${PATH}" ./scripts/init-repo.sh python --team automation --no-push 2>&1); then
  pass "no-remote path exits 0 (it is an answer: there is no repo to check yet)"
else
  fail "no-remote path should exit 0, got non-zero. Output: ${out}"
fi
assert_match "warns that write access is UNVERIFIED" 'UNVERIFIED' "$out"
assert_match "warns the file MAY BE INERT" 'MAY BE INERT' "$out"
assert_match "says GitHub silently ignores such an entry" 'silently ignores' "$out"
assert_file  "CODEOWNERS still written (with the caveat, not silently)" .github/CODEOWNERS
if [ -f .github/CODEOWNERS ]; then
  live="$(cat .github/CODEOWNERS)"
  assert_nomatch "live CODEOWNERS has no 'TEMPLATE — not live' preamble" 'TEMPLATE .. not live' "$live"
  assert_match   "live CODEOWNERS names the resolved team" '@Avenue-Z/automation' "$live"
  # The file must not CLAIM a verification that never happened — that is the same lie in
  # a different place.
  assert_match   "the file itself records that write access was NOT verified" 'could NOT verify' "$live"
  assert_nomatch "the file does not claim verified write access" 'AND holds write access' "$live"
fi
rm -rf "${STUB_NOREMOTE}"

echo "init-repo: 'gh repo view' fails for a NON-remote reason — must die, never write unverified"
STUB_APIFAIL="$(mktemp -d)"
cat > "${STUB_APIFAIL}/gh" <<'STUBEOF'
#!/usr/bin/env bash
case "$*" in
  *"repo view"*)
    echo '{"message":"Bad credentials","status":"401"}' >&2; exit 1 ;;
  *"orgs/Avenue-Z/teams/automation"*)
    echo '{"slug":"automation"}' ;;
  *)
    echo "fake gh: unexpected call: gh $*" >&2; exit 1 ;;
esac
STUBEOF
chmod +x "${STUB_APIFAIL}/gh"

cd "${WORK}" && rm -rf repo4b && git clone -q "${REPO_ROOT}" repo4b && cd repo4b
git checkout -qb dev 2>/dev/null || git checkout -q dev
if out=$(PATH="${STUB_APIFAIL}:${PATH}" ./scripts/init-repo.sh python --team automation --no-push 2>&1); then
  fail "a 401 from 'gh repo view' was silently treated as 'no remote' and CODEOWNERS was written. Output: ${out}"
else
  pass "a 401 from 'gh repo view' is fatal (non-zero exit) — a failure to verify is not a pass"
fi
assert_match   "says it cannot determine the target repo" 'cannot determine the target repo' "$out"
assert_no_file "no CODEOWNERS written when the repo could not be identified" .github/CODEOWNERS
assert_file    "CODEOWNERS.tmpl preserved" .github/CODEOWNERS.tmpl
rm -rf "${STUB_APIFAIL}"

# Criterion (Important 6) — HEAD must be dev; a single-branch 'Use this template' copy
# lands the init commit on main and then dies mid-flight on `git push dev`.
cd "${WORK}" && rm -rf repo5 && git clone -q "${REPO_ROOT}" repo5 && cd repo5
git checkout -qb main 2>/dev/null || git checkout -q main
if out=$(./scripts/init-repo.sh python --no-push 2>&1); then
  fail "ran with HEAD=main — dev would be left stale and the push would die after the commit"
else
  pass "refuses to run when HEAD is not dev"
fi
assert_match "says HEAD is not dev" "not 'dev'" "$out"
assert_dir   "died BEFORE mutating the tree (templates/ intact)" templates

# ---------------------------------------------------------------------------------------
# A team that EXISTS but lacks write access no longer just gets a warning — the script
# now GRANTS it write, because a warning nobody actions leaves every new repo with an
# inert CODEOWNERS (GitHub silently ignores an entry for a team without write). Drive
# both outcomes with a fake `gh` on PATH (pattern from template-tests/test_apply_rulesets.sh) so
# no real GitHub call is made.
echo "init-repo: team exists but lacks write — script grants it"
STUB_OK="$(mktemp -d)"
cat > "${STUB_OK}/gh" <<'STUBEOF'
#!/usr/bin/env bash
# Fake gh: team 'no-write-team' exists, starts without write, grant succeeds.
STATE="$(dirname "$0")"
case "$*" in
  *"-X PUT"*"permission=push"*)
    touch "${STATE}/.granted"
    echo '{"permission":"push"}' ;;
  *".permissions.push"*)
    if [ -f "${STATE}/.granted" ]; then echo true; else echo false; fi ;;
  *"orgs/Avenue-Z/teams/no-write-team"*)
    echo '{"slug":"no-write-team"}' ;;
  *nameWithOwner*)
    echo "Avenue-Z/fake-repo" ;;
  *)
    echo "fake gh: unexpected call: gh $*" >&2; exit 1 ;;
esac
STUBEOF
chmod +x "${STUB_OK}/gh"

cd "${WORK}" && rm -rf repo6 && git clone -q "${REPO_ROOT}" repo6 && cd repo6
git checkout -qb dev 2>/dev/null || git checkout -q dev
if out=$(PATH="${STUB_OK}:${PATH}" ./scripts/init-repo.sh python --team no-write-team --no-push 2>&1); then
  pass "grant-then-write path exits 0"
else
  fail "grant-then-write path should exit 0, got non-zero. Output: ${out}"
fi
assert_match   "reports it granted write access" 'granted.*no-write-team.*write access' "$out"
assert_file    "CODEOWNERS written after a successful grant" .github/CODEOWNERS
assert_no_file "CODEOWNERS.tmpl removed after a successful grant" .github/CODEOWNERS.tmpl
if [ -f .github/CODEOWNERS ]; then
  live_ok="$(cat .github/CODEOWNERS)"
  assert_match   "live CODEOWNERS names the real team" '@Avenue-Z/no-write-team' "$live_ok"
  assert_nomatch "live CODEOWNERS has no leftover TEAM_SLUG token" 'TEAM_SLUG' "$live_ok"
fi
rm -rf "${STUB_OK}"

echo "init-repo: grant FAILS with 403 — must die, not ship an inert CODEOWNERS"
STUB_403="$(mktemp -d)"
cat > "${STUB_403}/gh" <<'STUBEOF'
#!/usr/bin/env bash
# Fake gh: team 'no-write-team' exists, starts without write, grant is 403 Forbidden.
case "$*" in
  *"-X PUT"*"permission=push"*)
    echo '{"message":"Must have admin rights to Repository.","status":"403"}' >&2
    exit 1 ;;
  *".permissions.push"*)
    echo false ;;
  *"orgs/Avenue-Z/teams/no-write-team"*)
    echo '{"slug":"no-write-team"}' ;;
  *nameWithOwner*)
    echo "Avenue-Z/fake-repo" ;;
  *)
    echo "fake gh: unexpected call: gh $*" >&2; exit 1 ;;
esac
STUBEOF
chmod +x "${STUB_403}/gh"

cd "${WORK}" && rm -rf repo7 && git clone -q "${REPO_ROOT}" repo7 && cd repo7
git checkout -qb dev 2>/dev/null || git checkout -q dev
if out=$(PATH="${STUB_403}:${PATH}" ./scripts/init-repo.sh python --team no-write-team --no-push 2>&1); then
  fail "grant returning 403 should not exit 0. Output: ${out}"
else
  pass "grant returning 403 exits non-zero"
fi
assert_match   "explains a human needs repo-admin/org-owner rights to grant" 'repo-admin or org-owner' "$out"
assert_no_file "no CODEOWNERS written when the grant fails" .github/CODEOWNERS
assert_file    "CODEOWNERS.tmpl preserved when the grant fails" .github/CODEOWNERS.tmpl
rm -rf "${STUB_403}"

# ---------------------------------------------------------------------------------------
# THE "USE THIS TEMPLATE" FIRST RUN — main must NOT be left holding the uninitialized template.
#
# GitHub's "Use this template" hands you a repo whose ONLY branch is main. The documented next
# step is `git checkout -b dev`, so on a FIRST run a local `main` ALWAYS exists, exactly one
# commit behind dev. ensure_branches used to see "the branch exists" and leave it alone as drift
# — which left main, the PRODUCTION branch and GitHub's default, pointing at the RAW TEMPLATE:
# templates/, template-tests/ and the template's own spec and plan all still on it, while the
# script cheerfully printed "Done."
#
# None of the clones above can catch this. `git clone` gives them exactly one local branch, so
# ensure_branches takes the create-from-scratch path and main comes out right by accident. This
# test builds the single-branch layout by hand, because that is the one real users are handed.
echo "init-repo: first run from a 'Use this template' copy (local main pre-exists, behind dev)"
cd "${WORK}" && rm -rf repo8 && git clone -q "${REPO_ROOT}" repo8 && cd repo8
# -B, not -b, for BOTH. `git clone` gives the clone one local branch: whichever one REPO_ROOT has
# checked out. So `-b dev` fails with "a branch named 'dev' already exists" whenever the suite is
# run from dev — and silently works when run from a feature branch. That made this test's result
# depend on which branch the developer happened to be standing on, which is not a test at all.
# -B forces the branch to the right commit either way, so the fixture is the same everywhere.
git checkout -qB main                       # main: the only branch a template copy has
git checkout -qB dev                        # the documented next step
./scripts/init-repo.sh python --no-push >/dev/null 2>&1

if git ls-tree -r --name-only main | grep -qE '^templates/|^template-tests/'; then
  fail "main STILL carries the uninitialized template — the production branch was left behind"
else
  pass "main was fast-forwarded past the cleanup commit (no templates/, no template-tests/)"
fi
assert_eq "$(git rev-parse dev)" "$(git rev-parse main)"    "main is at dev after a first run"
assert_eq "$(git rev-parse dev)" "$(git rev-parse staging)" "staging is at dev after a first run"

# The other half: fast-forward is safe ONLY because the branch is an ancestor. A branch that has
# genuinely DIVERGED carries commits dev does not, and moving it would silently drop them. That
# one must still be left alone — "re-run repairs absence, not drift" is right for real drift.
echo "init-repo: a DIVERGED branch is left alone (fast-forward must not become a force-push)"
git checkout -q main
echo "a real commit that only main has" > main-only.txt
git add main-only.txt && git commit -q -m "chore: a commit that exists only on main"
diverged_sha="$(git rev-parse main)"
git checkout -q dev
echo "some later dev work" > dev-only.txt
git add dev-only.txt && git commit -q -m "chore: later dev work"
out=$(./scripts/init-repo.sh python --no-push 2>&1)
assert_eq "${diverged_sha}" "$(git rev-parse main)" "diverged main was NOT moved (its commit survives)"
assert_match "says main has diverged" 'DIVERGED' "$out"
assert_match "tells you to reconcile with a PR" 'Reconcile it by opening a PR' "$out"

finish
