#!/usr/bin/env bash
#
# Apply branch protection TO THIS REPO where the GitHub plan allows it, and say plainly where it
# does not.
#
#   ./scripts/apply-rulesets.sh [--dry-run]
#
# Branch protection and rulesets are UNAVAILABLE on private repos on the Free plan — for
# everyone, including org owners. This script never pretends otherwise: if it cannot protect a
# branch, it says so and exits 0.
#
# THIS SCRIPT ONLY EVER TOUCHES ONE REPO: the one you are standing in.
#
# The org-wide apply used to live here behind `--org`. It does not any more. It is
# scripts/apply-org-ruleset.sh, a separate script, precisely BECAUSE it sat one flag away from
# this routine command — a fat-finger, a stray tab-complete, or an Up-arrow through shell history
# was all that separated "protect my new repo" from "rewrite protection on all ~64 repos in the
# org". Nothing you can type here reaches that code.
#
set -euo pipefail

ORG="Avenue-Z"
DRY=0

warn() { printf '\033[33mWARN\033[0m  %s\n' "$*" >&2; }
info() { printf '\033[32m--\033[0m    %s\n' "$*"; }
die()  { printf '\033[31mERROR\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    # Name the removed flags explicitly. Someone typing them is working from memory or an old
    # runbook; "unknown flag" would leave them hunting for a typo instead of telling them the
    # org-wide apply deliberately moved out of reach.
    --org)     die "--org is gone from this script, by design. The org-wide apply is now its own
       command, so that it cannot be reached by a flag on the one you run routinely:

           ./scripts/apply-org-ruleset.sh --dry-run

       It applies to EVERY repo in ${ORG} and will make you type a challenge phrase." ;;
    --yes|-y)  die "there is no --yes on this script — it has nothing destructive to confirm.
       (If you are reaching for it out of habit: the org-wide apply moved to
       scripts/apply-org-ruleset.sh, and that one has no --yes either, on purpose.)" ;;
    *)         die "unknown flag '$1' (usage: apply-rulesets.sh [--dry-run])" ;;
  esac
done

# jq is a hard dependency (the payload is built with it). Without this check, `set -e`
# just aborts on the first jq call with no output at all and no hint why.
command -v jq >/dev/null 2>&1 || die "jq is required but not installed. Install it: brew install jq"
command -v gh >/dev/null 2>&1 || die "gh is required but not installed. Install it: brew install gh"

# EVERY plan-gated decision below hangs off this value, so a failure to GET it must not be
# laundered into a value. The old `|| echo unknown` did exactly that: auth expiry, a network
# blip or a rate limit all became "unknown", which is != "free", which SKIPS the honesty
# branch and walks straight into the POST. "I could not ask" is not "not on Free".
if ! PLAN="$(gh api "orgs/${ORG}" -q .plan.name 2>&1)"; then
  die "cannot determine the ${ORG} plan (auth? network? rate limit?): ${PLAN}
       Refusing to continue: every decision below depends on the plan, and guessing it
       wrong means either a false claim of protection or a bricked repo. Fix the cause
       (gh auth status) and re-run."
fi
[ -n "${PLAN}" ] && [ "${PLAN}" != "null" ] \
  || die "the ${ORG} plan came back empty — the token likely cannot read org details.
       Refusing to continue rather than assume you are not on Free.
       Try: gh auth refresh -h github.com -s read:org"
info "org plan: ${PLAN}"

# ----------------------------------------------------------------- repo ruleset
# Compute which status checks would be required. This is a purely local decision — it only
# depends on whether ci.yml exists in this working copy — so it is computed and shown up
# front, regardless of whether we can even reach GitHub to find out what repo we're in.
#
# Add 'ci' to the required checks ONLY if ci.yml is actually present. A required check
# that never reports does not fail the PR — it hangs PENDING forever, and nothing merges.
PAYLOAD="$(mktemp)"; trap 'rm -f "${PAYLOAD}"' EXIT
cp .github/rulesets/repo-ruleset.json "${PAYLOAD}"

# Add a context to the required checks ONLY if the workflow that reports it actually exists here.
# A required check that never reports does not fail a PR — it hangs it PENDING FOREVER, and
# nothing in the repo can be merged again. So both of these are conditional on a file, not on an
# assumption about which repo we are in.
#
#   ci             -> arrives with the stack, in a GENERATED repo (init-repo.sh copies it).
#   template-tests -> exists ONLY in repo-template itself. init-repo.sh DELETES it, so a generated
#                     repo must never require it. This is why the check is file-gated rather than
#                     baked into repo-ruleset.json, which both kinds of repo share.
add_context() { # <context> <workflow-file> <why-it-matters>
  if [ -f "$2" ]; then
    info "$2 present — adding '$1' to required checks"
    jq --arg c "$1" '(.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks)
        += [{"context":$c}]' "${PAYLOAD}" > "${PAYLOAD}.tmp" && mv "${PAYLOAD}.tmp" "${PAYLOAD}"
  else
    info "no $2 — not requiring '$1' ($3)"
  fi
}
add_context ci             .github/workflows/ci.yml             "a required check with no workflow hangs every PR pending forever"
add_context template-tests .github/workflows/template-tests.yml "this workflow is the template's own, and init-repo.sh removes it"
info "required status checks:"
jq -r '.rules[] | select(.type=="required_status_checks")
       | .parameters.required_status_checks[].context' "${PAYLOAD}" | sed 's/^/        required: /'

# Figure out which repo we're targeting. This requires a GitHub remote — if this working
# copy has none yet (e.g. it hasn't been pushed), say so plainly and stop. That is not a
# script bug; it's an honest report that there is nothing to apply protection to yet.
if ! REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)"; then
  warn "cannot determine target repo — no GitHub remote is configured for this working copy."
  warn "  Nothing was applied. This is expected before the repo is pushed to GitHub."
  exit 0
fi
VIS="$(gh repo view --json visibility -q .visibility)"
info "repo: ${REPO} (${VIS})"

if [ "${VIS}" != "PUBLIC" ] && [ "${PLAN}" = free ]; then
  warn "${REPO} is PRIVATE and ${ORG} is on the Free plan."
  warn "  Branch protection and rulesets are UNAVAILABLE here. Nothing was applied."
  warn "  main/staging/dev are NOT protected. A direct push to main will succeed."
  warn "  Enforcement in this repo is: guard-base-branch + secret-scan on PRs, and convention."
  warn "  To get real protection: make this repo public, or upgrade ${ORG} to GitHub Team."
  exit 0                       # NOT an error — an honest report of a plan limit.
fi

NAME="$(jq -r '.name' "${PAYLOAD}")"

# GitHub allows multiple rulesets with the same name — a plain POST every run would create a
# duplicate instead of updating the one already in force. Look up an existing ruleset by name
# first. A failed lookup is NOT "no existing ruleset": if we can't ask, we must not guess, or
# we risk silently creating a diverging duplicate. Die instead.
if ! LIST="$(gh api "repos/${REPO}/rulesets" 2>&1)"; then
  die "cannot list existing rulesets for ${REPO} (auth? network? rate limit?): ${LIST}
       Refusing to continue: without the existing list we cannot tell whether '${NAME}'
       already exists, and POSTing blind risks creating a duplicate ruleset that silently
       diverges from it. Fix the cause (gh auth status) and re-run."
fi
EXISTING_ID="$(printf '%s' "${LIST}" | jq -r --arg name "${NAME}" '[.[] | select(.name==$name)][0].id // empty')"

if [ "${DRY}" -eq 1 ]; then
  if [ -n "${EXISTING_ID}" ]; then
    info "[dry-run] would PUT repos/${REPO}/rulesets/${EXISTING_ID} (update existing '${NAME}') with the required checks listed above"
  else
    info "[dry-run] would POST repos/${REPO}/rulesets (create new '${NAME}') with the required checks listed above"
  fi
  exit 0
fi

if [ -n "${EXISTING_ID}" ]; then
  gh api -X PUT "repos/${REPO}/rulesets/${EXISTING_ID}" --input "${PAYLOAD}" >/dev/null \
    || die "ruleset PUT failed for ${REPO} (id ${EXISTING_ID})"
  info "updated existing ruleset '${NAME}' (id ${EXISTING_ID}) on ${REPO} — main, staging, dev."
else
  gh api -X POST "repos/${REPO}/rulesets" --input "${PAYLOAD}" >/dev/null \
    || die "ruleset POST failed for ${REPO}"
  info "created new ruleset '${NAME}' on ${REPO} — main, staging, dev."
fi
info "Verify you can still merge:  gh api repos/${REPO}/branches/main/protection"
