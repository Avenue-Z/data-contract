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
