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
