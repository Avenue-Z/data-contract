#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=template-tests/lib.sh disable=SC1091
source template-tests/lib.sh

WORKFLOW=.github/workflows/secret-scan.yml
PRECOMMIT=.pre-commit-config.yaml

# secret-scan is the ONLY control that actually blocks a credential from reaching a protected
# branch — the pre-commit hook is local and skippable with --no-verify, and private repos on
# Free have no server-side push protection. It had no test at all, which meant it could be
# defanged silently: flipping `--exit-code 1` to `--exit-code 0` makes gitleaks report findings
# and exit 0, so the job goes GREEN on a PR that leaks a key. Deleting the checksum step lets a
# tampered or 404'd download run as root. Neither left a mark on any suite.

echo "secret-scan: the job exists and is named exactly what the rulesets require"
assert_file "$WORKFLOW exists" "$WORKFLOW"
wf="$(cat "$WORKFLOW")"
if grep -A1 '^jobs:' "$WORKFLOW" | tail -1 | grep -q '^  secret-scan:$'; then
  pass "jobs key is literally secret-scan"
else
  fail "jobs key must be literally 'secret-scan' (the ruleset requires that exact context)"
fi

echo "secret-scan: gitleaks must FAIL the job on a finding"
# --exit-code 1 is the entire control. Without it (or with 0), gitleaks prints the leak and
# exits 0, and the required check goes green on a PR that ships a live credential.
if grep -qE 'gitleaks +detect[^|]*--exit-code +1' <<<"$wf"; then
  pass "gitleaks detect is invoked with --exit-code 1"
else
  fail "gitleaks detect must be invoked with '--exit-code 1' — without it a leak passes the check"
fi
assert_nomatch "no --exit-code 0 anywhere (that would make every finding a pass)" '[-]-exit-code +0' "$wf"

# ---------------------------------------------------------------------------------------
# SCOPE. `gitleaks detect` with no --log-opts scans EVERY commit in the repo, not the change
# under review. So one secret committed once — even one long since deleted AND rotated — fails
# every subsequent PR forever, however innocent: the repo becomes permanently unmergeable, and
# rotating the key (the remedy SECURITY.md prescribes) does not clear it. Only a history rewrite
# does. Verified: an untouched feature branch off a history containing a since-removed token
# exits 1 under the unscoped command.
#
# The PR path must therefore scan the PR's own range; the push path keeps the full-history audit.
echo "secret-scan: a PR must scan the commits it ADDS, not the whole repo history"
assert_match "the PR path scopes the scan with --log-opts" '[-]-log-opts' "$wf"
if grep -qE '[-]-log-opts "origin/\$\{BASE_REF\}\.\.HEAD"' <<<"$wf"; then
  pass "the scope is exactly the PR range (origin/\${BASE_REF}..HEAD)"
else
  fail "the PR scan must be scoped to 'origin/\${BASE_REF}..HEAD' — an unscoped detect blocks every future PR once any secret enters history"
fi
# base_ref is attacker-influenced input, and ${{ }} inside `run:` is textual substitution, not a
# shell variable — a ref name is not safe to splice into the script body.
if grep -qE 'BASE_REF: \$\{\{ *github\.base_ref *\}\}' <<<"$wf"; then
  pass "base_ref reaches the script through env:, not interpolated into run:"
else
  fail "github.base_ref must be passed via env: (BASE_REF), never interpolated directly into a run: block"
fi
# The full scan must survive for pushes — that is where a repo-wide audit belongs.
assert_match "fetch-depth: 0 retained (origin/<base> must resolve, and push scans all history)" 'fetch-depth: *0' "$wf"

echo "secret-scan: the download must be verified before it is run as root"
assert_match "downloads a checksums file" 'checksums\.txt' "$wf"
assert_match "verifies the checksum with sha256sum -c" 'sha256sum .*-c ' "$wf"
# --ignore-missing verifies NOTHING (and errors) if the asset is not on disk under the exact
# filename checksums.txt lists. So the check is only real if the file we downloaded is named
# ${ASSET} — the same name the checksums file refers to. Assert the download names that file,
# rather than, say, gitleaks.tar.gz, which would make the whole verification vacuous.
if grep -qE '^ *curl .*o "\$\{ASSET\}" "\$\{BASE_URL\}/\$\{ASSET\}"' <<<"$wf"; then
  pass "the asset is downloaded under the exact filename checksums.txt lists (\${ASSET})"
else
  fail "the asset must be downloaded as \${ASSET} — sha256sum --ignore-missing verifies nothing if the filename does not match checksums.txt"
fi
assert_match "the verified asset is the one extracted" 'tar -xzf "\$\{ASSET\}"' "$wf"

echo "secret-scan: curl must --fail (a 404 otherwise writes an HTML error page to disk)"
# Count real invocations only — a line that merely mentions curl in a comment is not a call.
curl_lines="$(grep -cE '^ *curl ' <<<"$wf" || true)"
curl_fail_lines="$(grep -cE '^ *curl .*--fail' <<<"$wf" || true)"
assert_eq "$curl_lines" "$curl_fail_lines" "every curl invocation ($curl_lines) uses --fail"

echo "secret-scan: the gitleaks version must be the SAME in the workflow and the pre-commit hook"
# Nothing else keeps these in sync. A drifted pair means the hook a developer runs locally is
# not the scanner that gates the PR — different rule sets, different findings, and a leak that
# passes locally and surprises them in CI (or worse, the reverse).
wf_ver="$(grep -oE 'GITLEAKS_VERSION="[0-9.]+"' "$WORKFLOW" | grep -oE '[0-9.]+' || true)"
pc_ver="$(grep -A1 'gitleaks/gitleaks' "$PRECOMMIT" | grep -oE 'rev: *v[0-9.]+' | grep -oE '[0-9.]+' || true)"
if [ -z "$wf_ver" ]; then fail "could not read GITLEAKS_VERSION from $WORKFLOW"; fi
if [ -z "$pc_ver" ]; then fail "could not read the gitleaks rev from $PRECOMMIT"; fi
assert_eq "$wf_ver" "$pc_ver" "gitleaks version matches: $WORKFLOW ($wf_ver) == $PRECOMMIT (v$pc_ver)"

echo "secret-scan: the workflow must not grant itself write"
assert_match "declares a top-level permissions block" 'permissions:' "$wf"
assert_match "contents: read" 'contents: *read' "$wf"

finish
