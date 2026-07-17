#!/usr/bin/env bash
#
# Apply org-ruleset.json to EVERY REPOSITORY IN THE Avenue-Z ORG.
#
#   ./scripts/apply-org-ruleset.sh [--dry-run]
#
# ---------------------------------------------------------------------------------------------
# THIS IS THE HIGHEST-BLAST-RADIUS COMMAND IN THIS REPO. IT IS DELIBERATELY HARD TO RUN.
# ---------------------------------------------------------------------------------------------
#
# It exists as a SEPARATE SCRIPT on purpose. It used to be `apply-rulesets.sh --org` — one flag
# away from the command you run on every new repo. That adjacency was the whole problem:
#
#   * a fat-finger or a stray tab-complete could turn a routine per-repo apply into an org-wide one
#   * `[y/N]` is answered by reflex; `y` is muscle memory, not consent
#   * `apply-rulesets.sh --org --yes` lived in shell history forever, one Up-arrow from re-firing
#
# So the three defences here are, in order:
#
#   1. IT IS ITS OWN SCRIPT. There is no flag on the routine command that reaches this code. You
#      cannot get here by accident from `apply-rulesets.sh`.
#
#   2. THERE IS NO `--yes`, AND NO NON-INTERACTIVE PATH AT ALL. You must type a challenge phrase,
#      in full, that names the LIVE repo count. It is read from stdin, so it never lands in shell
#      history — there is nothing to Up-arrow into. And because the count is interpolated live, a
#      phrase memorised or copy-pasted from a doc goes STALE the moment the org grows. This script
#      must never run from CI, and it cannot.
#
#   3. A BRICKING PAYLOAD IS REFUSED OUTRIGHT, not warned about. See the check below.
#
# Why so much ceremony: this ruleset targets repository_name ~ALL with enforcement=active and
# bypass_actors=[]. Applied carelessly it takes push AND merge away from every repo in Avenue-Z
# at once — including the ~60 that never came from this template.
#
set -euo pipefail

ORG="Avenue-Z"
SRC=".github/rulesets/org-ruleset.json"
DRY=0

warn() { printf '\033[33mWARN\033[0m  %s\n' "$*" >&2; }
info() { printf '\033[32m--\033[0m    %s\n' "$*"; }
die()  { printf '\033[31mERROR\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    # --yes / -y are GONE, and naming them explicitly is better than "unknown flag": someone
    # reaching for them is working from memory or an old runbook, and deserves to be told why
    # the bypass no longer exists rather than left guessing at a typo.
    --yes|-y)  die "there is no --yes on this script, by design.
       An org-wide ruleset apply is not something you consent to with a flag — a flag can be
       fat-fingered, copy-pasted from a runbook, or replayed out of shell history. You must type
       the challenge phrase this script prints, interactively. If you are trying to run this from
       CI or a script: don't. That is exactly what this refusal is for." ;;
    --org)     die "you are already running the org script — drop the --org flag." ;;
    *)         die "unknown flag '$1' (usage: apply-org-ruleset.sh [--dry-run])" ;;
  esac
done

command -v jq >/dev/null 2>&1 || die "jq is required but not installed. Install it: brew install jq"
command -v gh >/dev/null 2>&1 || die "gh is required but not installed. Install it: brew install gh"
[ -f "${SRC}" ] || die "${SRC} not found — run this from the repo root."

# Every plan-gated decision below hangs off this value, so a failure to GET it must not be
# laundered into a value. "I could not ask" is not "not on Free".
if ! PLAN="$(gh api "orgs/${ORG}" -q .plan.name 2>&1)"; then
  die "cannot determine the ${ORG} plan (auth? network? rate limit?): ${PLAN}
       Refusing to continue: guessing the plan wrong means either a false claim of protection
       or a bricked org. Fix the cause (gh auth status) and re-run."
fi
[ -n "${PLAN}" ] && [ "${PLAN}" != "null" ] \
  || die "the ${ORG} plan came back empty — the token likely cannot read org details.
       Try: gh auth refresh -h github.com -s read:org"
info "org plan: ${PLAN}"

if [ "${PLAN}" = free ]; then
  warn "org-level rulesets require GitHub Team. On Free they cannot be created."
  warn "  The ruleset is committed at ${SRC}, ready to apply on upgrade."
  exit 0                       # NOT an error — an honest report of a plan limit.
fi

NAME="$(jq -r '.name' "${SRC}")"

# `_comment` is documentation for humans, not a GitHub API field. Strip it before sending.
PAYLOAD="$(mktemp)"; trap 'rm -f "${PAYLOAD}"' EXIT
jq 'del(._comment)' "${SRC}" > "${PAYLOAD}"

# ---------------------------------------------------------------- defence 3: refuse, don't warn
# A required status check that no workflow ever reports does NOT fail a PR. It hangs the PR
# PENDING FOREVER — unmergeable, with no error anyone can act on. Combined with enforcement:active
# and bypass_actors:[], ONE run of this script would take push AND merge away from every repo in
# the org simultaneously, while printing a success message.
#
# The old code merely WARNED about this and carried on. A warning is not a control — that is the
# lesson of this entire repo. If org-ruleset.json declares required checks, we do not ask the
# operator to be careful. We refuse.
CHECKS="$(jq -r '[.rules[] | select(.type=="required_status_checks")] | length' "${PAYLOAD}")"
if [ "${CHECKS}" != "0" ]; then
  printf '\n'
  jq -r '.rules[] | select(.type=="required_status_checks")
         | .parameters.required_status_checks[].context' "${PAYLOAD}" | sed 's/^/        required: /'
  die "${SRC} declares required status checks (listed above), and this ruleset targets ~ALL repos.

       REFUSING. Almost no repo in ${ORG} ships those workflows. A required check that never
       reports does not fail a PR — it hangs it PENDING FOREVER. Applying this would make every
       repo in the org permanently unmergeable, all at once, and this script would print success.

       Required checks belong in .github/rulesets/repo-ruleset.json, applied per-repo by
       scripts/apply-rulesets.sh to repos that actually ship the workflows. That is the correct
       scope for them. Remove the required_status_checks rule from ${SRC} and re-run."
fi

# ------------------------------------------------------------------- blast radius, stated first
if ! REPOS="$(gh api "orgs/${ORG}/repos" --paginate -q '.[].name' 2>&1)"; then
  die "cannot list the repos in ${ORG} (auth? network? rate limit?): ${REPOS}
       Refusing to continue: this script applies a ruleset to EVERY repo in the org, and it will
       not do that without first showing you which repos those are."
fi
COUNT="$(printf '%s\n' "${REPOS}" | grep -c . || true)"
[ "${COUNT}" -gt 0 ] || die "${ORG} reported zero repositories — that cannot be right. Refusing to continue."

printf '\n'
info "This applies '${NAME}' to EVERY repository in ${ORG} — ${COUNT} of them:"
printf '%s\n' "${REPOS}" | sed 's/^/        /'
printf '\n'
warn "Read this before you answer:"
warn "  * Every repo above gets enforcement=active with NO bypass actors — not even an org owner"
warn "    can push directly to main, staging or dev afterwards. Everything goes via a PR."
warn "  * Most of these repos did NOT come from repo-template and have no CI workflows at all."
warn "  * This ruleset ships NO required status checks, and this script refuses to apply one that"
warn "    does — that is the one mistake that would brick all ${COUNT} repos at once."
printf '\n'

# GitHub allows multiple rulesets with the same name — a plain POST every run would create a
# duplicate instead of updating the one already in force. A failed lookup is NOT "no existing
# ruleset": if we cannot ask, we must not guess, or we risk a silently diverging duplicate.
if ! LIST="$(gh api "orgs/${ORG}/rulesets" 2>&1)"; then
  die "cannot list existing rulesets for ${ORG} (auth? network? rate limit?): ${LIST}
       Refusing to continue: without the existing list we cannot tell whether '${NAME}' already
       exists, and POSTing blind risks creating a duplicate that silently diverges from it."
fi
EXISTING_ID="$(printf '%s' "${LIST}" | jq -r --arg name "${NAME}" '[.[] | select(.name==$name)][0].id // empty')"

if [ "${DRY}" -eq 1 ]; then
  if [ -n "${EXISTING_ID}" ]; then
    info "[dry-run] would PUT orgs/${ORG}/rulesets/${EXISTING_ID} (update existing '${NAME}') from ${SRC}"
  else
    info "[dry-run] would POST orgs/${ORG}/rulesets (create new '${NAME}') from ${SRC}"
  fi
  info "[dry-run] nothing was applied."
  exit 0
fi

# ------------------------------------------------- defence 2: a typed challenge phrase, no flags
# The phrase names the LIVE repo count, so a phrase copied from a runbook or remembered from last
# quarter is WRONG once the org has grown — and being wrong here means the script refuses, which
# is the safe direction. Reading it from stdin (not argv) keeps it out of shell history entirely.
#
# No tty => no consent. There is no environment variable, no flag, and no piped-input path that
# reaches the apply below. If you are trying to automate this, the answer is no.
PHRASE="apply ${NAME} to all ${COUNT} repos in ${ORG}"
if [ ! -t 0 ]; then
  die "stdin is not a terminal, so you cannot be asked to confirm — and there is no flag that
       skips the question. This script cannot run unattended, by design.

       To apply it, run it yourself in a terminal and type the challenge phrase when asked.
       To see the plan without applying it: $0 --dry-run"
fi

printf 'To apply this to all %s repos in %s, type the phrase below EXACTLY.\n' "${COUNT}" "${ORG}"
printf 'Anything else aborts.\n\n'
printf '    %s\n\n' "${PHRASE}"
printf '> '
IFS= read -r reply || reply=""

if [ "${reply}" != "${PHRASE}" ]; then
  info "phrase did not match — aborted. NOTHING was applied."
  exit 0
fi

if [ -n "${EXISTING_ID}" ]; then
  gh api -X PUT "orgs/${ORG}/rulesets/${EXISTING_ID}" --input "${PAYLOAD}" >/dev/null \
    || die "org ruleset update failed. Need the admin:org scope? gh auth refresh -h github.com -s admin:org"
  info "updated existing org ruleset '${NAME}' (id ${EXISTING_ID}) — all ${COUNT} repos in ${ORG} now inherit it."
else
  gh api -X POST "orgs/${ORG}/rulesets" --input "${PAYLOAD}" >/dev/null \
    || die "org ruleset create failed. Need the admin:org scope? gh auth refresh -h github.com -s admin:org"
  info "created new org ruleset '${NAME}' — all ${COUNT} repos in ${ORG} now inherit it."
fi
info "Verify a repo can still merge:  gh api repos/${ORG}/<repo>/rulesets"
