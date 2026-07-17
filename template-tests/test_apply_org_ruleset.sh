#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=template-tests/lib.sh disable=SC1091
source template-tests/lib.sh

SCRIPT=./scripts/apply-org-ruleset.sh

# scripts/apply-org-ruleset.sh is the highest-blast-radius command in this repo: it applies a
# ruleset with enforcement=active and bypass_actors=[] to EVERY repository in Avenue-Z. Its whole
# value is that it is HARD TO RUN BY ACCIDENT. These tests defend the three things that make it
# hard, because each one is the kind of "friction" a future reader is tempted to file off:
#
#   1. it is a SEPARATE SCRIPT (no flag on the routine command reaches it) — asserted in
#      test_apply_rulesets.sh, which checks --org is refused there and the code is gone
#   2. there is NO --yes and NO non-interactive path; you must TYPE a challenge phrase
#   3. a payload with required_status_checks is REFUSED, not warned about

assert_file "$SCRIPT exists" "$SCRIPT"
assert_ok   "$SCRIPT is executable" test -x "$SCRIPT"

# A stub gh: org on Team (so the Free-plan honesty exit is not hit), 3 repos, no existing ruleset.
STUB="$(mktemp -d)"
trap 'rm -rf "${STUB}"' EXIT
cat > "${STUB}/gh" <<'STUBEOF'
#!/usr/bin/env bash
case "$*" in
  *"orgs/Avenue-Z/repos"*)     printf 'ad-spend-pacing\ndrive-api-client\naivx-reports\n' ;;
  *"orgs/Avenue-Z/rulesets"*)
    # A POST/PUT is an APPLY. Record it so the tests can prove it did (or did not) happen.
    case "$*" in
      *"-X POST"*|*"-X PUT"*) echo "APPLIED" >> "${ORG_STUB_LOG}" ; echo '{"id":999}' ;;
      *)                      echo '[]' ;;
    esac ;;
  *"orgs/Avenue-Z"*)           echo team ;;
  *) echo "fake gh: unexpected call: gh $*" >&2; exit 1 ;;
esac
STUBEOF
chmod +x "${STUB}/gh"

export ORG_STUB_LOG="${STUB}/applied.log"
: > "${ORG_STUB_LOG}"
# This prefix is spliced into a command string that lib.sh's pty_run runs via `bash -c`. Do NOT
# bake ${PATH} in raw: a host PATH with a space in it (e.g. macOS's ".../Application Support")
# splits the assignment into a bogus command word and the whole pty exec fails with 127. Quote the
# stub segment and let the INNER shell expand $PATH, the same way test_link_vercel.sh's run_linked
# does. The single quotes also protect a spaced ${STUB}/${ORG_STUB_LOG} from mktemp under $TMPDIR.
STUB_PATH="PATH='${STUB}:'\"\$PATH\" ORG_STUB_LOG='${ORG_STUB_LOG}'"

applied() { [ -s "${ORG_STUB_LOG}" ]; }
reset_log() { : > "${ORG_STUB_LOG}"; }

# ---------------------------------------------------------------------------------------
echo "apply-org-ruleset: --dry-run shows the blast radius and applies NOTHING"
reset_log
if out_dry=$(PATH="${STUB}:${PATH}" $SCRIPT --dry-run </dev/null 2>&1); then
  pass "--dry-run exits 0"
else
  fail "--dry-run should exit 0. Output: ${out_dry}"
fi
assert_match   "lists the repos it would affect" 'ad-spend-pacing' "$out_dry"
assert_match   "says EVERY repository" 'EVERY repository in Avenue-Z' "$out_dry"
assert_match   "states the live count" '3 of them' "$out_dry"
assert_match   "says there are no bypass actors" 'NO bypass actors' "$out_dry"
if applied; then fail "--dry-run APPLIED the ruleset"; else pass "--dry-run applied nothing"; fi

# ---------------------------------------------------------------------------------------
# DEFENCE 2 — no --yes, and no non-interactive path AT ALL.
echo "apply-org-ruleset: --yes does not exist (a flag is not consent)"
reset_log
if out_yes=$(PATH="${STUB}:${PATH}" $SCRIPT --yes </dev/null 2>&1); then
  fail "--yes was accepted — the consent bypass is back. Output: ${out_yes}"
else
  pass "--yes is refused"
fi
assert_match "explains why there is no --yes" 'no --yes on this script, by design' "$out_yes"
if applied; then fail "--yes APPLIED the ruleset"; else pass "--yes applied nothing"; fi

echo "apply-org-ruleset: a non-tty (CI, pipe, cron) can NEVER apply"
reset_log
if out_notty=$(PATH="${STUB}:${PATH}" $SCRIPT </dev/null 2>&1); then
  fail "ran to completion with no terminal — it must refuse. Output: ${out_notty}"
else
  pass "no tty => refuses (non-zero exit)"
fi
assert_match   "says it cannot run unattended" 'cannot run unattended' "$out_notty"
assert_nomatch "offers no flag to skip the question" 'use --yes|pass --yes' "$out_notty"
if applied; then fail "non-tty run APPLIED the ruleset"; else pass "non-tty run applied nothing"; fi

# Piping the phrase in must ALSO fail — otherwise `echo "..." | apply-org-ruleset.sh` is a
# one-liner that lives in shell history, which is precisely what the tty requirement prevents.
echo "apply-org-ruleset: piping the correct phrase must STILL fail (no tty = no consent)"
reset_log
if out_pipe=$(PATH="${STUB}:${PATH}" $SCRIPT <<<"apply avenue-z-branch-protection-org to all 3 repos in Avenue-Z" 2>&1); then
  fail "a piped phrase was accepted — that is a history-replayable one-liner. Output: ${out_pipe}"
else
  pass "a piped phrase is still refused (stdin is not a terminal)"
fi
if applied; then fail "piped phrase APPLIED the ruleset"; else pass "piped phrase applied nothing"; fi

# ---------------------------------------------------------------------------------------
# THE PHRASE ITSELF. These run over a REAL pty (see pty_run in lib.sh) — the only way to reach
# the apply path, which is the point of the design.
PHRASE="apply avenue-z-branch-protection-org to all 3 repos in Avenue-Z"

echo "apply-org-ruleset: a wrong phrase aborts and applies nothing"
reset_log
# Guard the capture. pty_run now propagates the child's exit code, so a bare `out=$(pty_run ...)`
# under `set -euo pipefail` would abort THIS ENTIRE FILE — skipping Defence 3, the bricking-payload
# refusal below — if the pty ever exits non-zero. A wrong phrase itself exits 0 (an honest decline),
# so any non-zero here is a harness failure, and it must fail loudly, not silently swallow the file.
if ! out_wrong="$(pty_run "y" "${STUB_PATH} ${SCRIPT}")"; then
  fail "pty_run failed before the wrong-phrase check — the harness aborted, Defence 3 never ran. Output: ${out_wrong}"
fi
assert_match "prints the phrase the operator must type" "${PHRASE}" "$out_wrong"
assert_match "aborts on a wrong answer" 'did not match' "$out_wrong"
if applied; then fail "a bare 'y' APPLIED the ruleset — muscle memory must not be enough"; else pass "'y' is NOT enough (applied nothing)"; fi

echo "apply-org-ruleset: a STALE phrase (wrong repo count) is refused"
# The live count is interpolated into the phrase precisely so a phrase copied from a runbook or
# remembered from last quarter goes WRONG as the org grows — and wrong means refuse.
reset_log
if ! out_stale="$(pty_run "apply avenue-z-branch-protection-org to all 64 repos in Avenue-Z" "${STUB_PATH} ${SCRIPT}")"; then
  fail "pty_run failed before the stale-phrase check — the harness aborted, Defence 3 never ran. Output: ${out_stale}"
fi
assert_match "a phrase with a stale count aborts" 'did not match' "$out_stale"
if applied; then fail "a stale-count phrase APPLIED the ruleset"; else pass "a stale-count phrase applied nothing"; fi

echo "apply-org-ruleset: the EXACT phrase, typed at a terminal, is what applies it"
reset_log
if ! out_ok="$(pty_run "${PHRASE}" "${STUB_PATH} ${SCRIPT}")"; then
  fail "pty_run failed on the exact-phrase happy path — the harness aborted, Defence 3 never ran. Output: ${out_ok}"
fi
assert_match "reports it created the org ruleset" 'created new org ruleset' "$out_ok"
if applied; then pass "the exact phrase DID apply it (the happy path still works)"; else fail "the exact phrase did not apply — the script is now unusable. Output: ${out_ok}"; fi

# ---------------------------------------------------------------------------------------
# DEFENCE 3 — a bricking payload is REFUSED, not warned about.
#
# A required status check that no workflow reports does not fail a PR; it hangs it PENDING
# FOREVER. Applied to ~ALL repos with enforcement:active and no bypass actors, that makes the
# entire org unmergeable in one shot. The old code printed a warning and carried on. A warning is
# not a control.
echo "apply-org-ruleset: a payload with required_status_checks is REFUSED (would brick every repo)"
BRICK="$(mktemp -d)"
mkdir -p "${BRICK}/.github/rulesets" "${BRICK}/scripts"
cp scripts/apply-org-ruleset.sh "${BRICK}/scripts/"
jq '.rules += [{"type":"required_status_checks","parameters":{"strict_required_status_checks_policy":false,"required_status_checks":[{"context":"ci"}]}}]' \
   .github/rulesets/org-ruleset.json > "${BRICK}/.github/rulesets/org-ruleset.json"

reset_log
if out_brick="$(cd "${BRICK}" && PATH="${STUB}:${PATH}" ORG_STUB_LOG="${ORG_STUB_LOG}" ./scripts/apply-org-ruleset.sh --dry-run </dev/null 2>&1)"; then
  fail "a ruleset with required checks was ACCEPTED — this would brick every repo in the org. Output: ${out_brick}"
else
  pass "a ruleset with required checks is refused (non-zero exit)"
fi
assert_match   "names the check that would brick the org" 'required: ci' "$out_brick"
assert_match   "explains it would hang PRs pending forever" 'PENDING FOREVER' "$out_brick"
assert_match   "says required checks belong in repo-ruleset.json" 'repo-ruleset\.json' "$out_brick"
if applied; then fail "the bricking payload APPLIED"; else pass "the bricking payload applied nothing"; fi
# It must refuse even on --dry-run: a dry-run that says "looks fine" trains the operator to trust
# a payload that would in fact take the org down.
assert_nomatch "does not report a clean plan for a bricking payload" 'would POST|would PUT' "$out_brick"
rm -rf "${BRICK}"

finish
