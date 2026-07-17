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
core_pins="$(pins "${CORE_WF[@]}" || true)"
tmpl_pins="$(pins "${TMPL_WF[@]}" || true)"

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
