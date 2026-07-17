#!/usr/bin/env bash
#
# Link this repo to a Vercel project. Linking only — this script NEVER deploys.
#
#   ./scripts/link-vercel.sh [--dry-run]
#
# ---------------------------------------------------------------------------------------------
# LINKING IS EASY. DEPLOYING IS A REVIEWED CODE CHANGE. That split is the whole design.
# ---------------------------------------------------------------------------------------------
#
# This script will:
#   * check you are logged into the Vercel CLI (it will NOT log you in — that is yours to do)
#   * REFUSE to link unless the repo's default branch is `main` (see why, below)
#   * run `vercel link` (interactive: you pick the scope and the project)
#   * establish that the production branch really is `main`, and REFUSE to finish if it is not:
#       - with VERCEL_TOKEN set, by asking the documented REST API (a real, machine-made check)
#       - without it, by making YOU read Branch Tracking in the dashboard and type what you see,
#         because the Vercel CLI genuinely cannot report it (no vercel command emits JSON)
#
# It will NOT:
#   * run `vercel deploy`, ever, under any flag
#   * enable any branch for deployment
#   * "fix" a wrong production branch behind your back
#   * claim to have verified something it did not. If it cannot check, it says so and makes a human
#     check — it never warns and carries on. (An earlier version did exactly that, and the check it
#     was "doing" could never have fired: it called `vercel project inspect --json`, a flag the CLI
#     does not have. template-tests/test_link_vercel.sh now contract-tests the CLI surface so an
#     invented flag fails the suite instead of silently disabling the control.)
#
# WHY THE PRODUCTION-BRANCH CHECK IS THE POINT OF THIS SCRIPT
#
# Vercel picks the production branch from `main`, `master`, or THE REPOSITORY'S DEFAULT BRANCH.
# There is NO documented API to set it — only an undocumented endpoint the dashboard calls.
# Vercel's own official workaround is "use the repository default branch".
#
# This template's default branch is `main` precisely so that Vercel's default is CORRECT. If the
# default branch is ever changed back to `dev`, then `dev` becomes the production branch, and
# EVERY MERGE TO dev DEPLOYS STRAIGHT TO PRODUCTION — bypassing staging, inverting the entire
# branch flow, silently. No error, no warning. That is the failure this check exists to catch.
#
# So we verify rather than assume, and a failure to verify is never treated as a verified pass.
#
# DEPLOYS ARE OFF UNTIL A HUMAN TURNS THEM ON
#
# vercel.json ships `"git": {"deploymentEnabled": false}`. Vercel treats every UNSPECIFIED branch
# as deployable, so `false` is the only posture that is safe by default. Enabling a branch means
# editing vercel.json — which means a PR, which means review and the branch flow. Runaway deploys
# are not prevented here by a warning nobody reads; they are prevented by the fact that turning a
# deploy on is a reviewed change to a tracked file.
#
set -euo pipefail

DRY=0
PROD_BRANCH="main"

warn() { printf '\033[33mWARN\033[0m  %s\n' "$*" >&2; }
info() { printf '\033[32m--\033[0m    %s\n' "$*"; }
die()  { printf '\033[31mERROR\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    *)         die "unknown flag '$1' (usage: link-vercel.sh [--dry-run])" ;;
  esac
done

command -v vercel >/dev/null 2>&1 || die "the Vercel CLI is not installed. Install it: npm i -g vercel"
command -v gh     >/dev/null 2>&1 || die "gh is required but not installed. Install it: brew install gh"
command -v jq     >/dev/null 2>&1 || die "jq is required but not installed. Install it: brew install jq"

[ -f vercel.json ] || die "no vercel.json here. This script is for the 'next' stack — run it from
       the repo root of a repo initialised with: ./scripts/init-repo.sh next"

# ------------------------------------------------------------------ the deploys-off invariant
# Check this BEFORE linking. If vercel.json does not disable deployments, then linking the project
# is the moment deploys start firing — and by then it is too late to warn about it.
# Classify what vercel.json says about deploys with jq (a hard dependency, checked above) — NOT a
# raw grep. The success message below tells operators to switch to the per-branch OBJECT form to
# turn deploys ON, and a text match for `"deploymentEnabled": false` cannot tell that deliberate,
# reviewed config apart from a missing key. `|| echo unsafe` fails closed on a malformed file.
#   off        -> the normal path: link with deploys off, verify, and let a later PR enable them.
#   per-branch -> deploys are already enabled deliberately. Refuse HONESTLY (see below), not as if
#                 it were an accident, and change nothing.
#   unsafe     -> true, missing, or unparseable: Vercel treats unspecified branches as deployable,
#                 so linking now is the runaway-deploy moment this file exists to prevent.
deploy_state="$(jq -r '
  .git.deploymentEnabled as $d
  | if ($d == false) then "off" elif (($d | type) == "object") then "per-branch" else "unsafe" end
' vercel.json 2>/dev/null || echo unsafe)"
case "${deploy_state}" in
  off) info "vercel.json disables deployments — linking will not start any deploys" ;;
  per-branch)
    die "vercel.json already enables deploys per-branch (the \"deploymentEnabled\" object form).

       NOT LINKING, and nothing was changed. This script links with deploys OFF as a gate — it is
       meant to run BEFORE you enable deploys, not after. A repo already carrying the object form
       has passed that gate, so there is nothing here for it to link safely. To re-verify an
       existing link (that production-branch tracking is still correct), check by hand:
           Vercel dashboard -> Project -> Settings -> Environments -> Production -> Branch Tracking" ;;
  *)
    die "vercel.json does not carry \"deploymentEnabled\": false.

       REFUSING TO LINK. Vercel treats every UNSPECIFIED branch as deployable, so linking now
       would start deploying on the next push — including a production deploy. If you genuinely
       mean to enable deploys, do it as a reviewed PR that says so, and link afterwards." ;;
esac

# ------------------------------------------------------------------------- the human gate
# vercel link is interactive (scope + project selection) and requires a real login. We refuse to
# run unattended: linking a repo to a deploy target is not something a CI job should do on its own.
if [ "${DRY}" -eq 0 ] && [ ! -t 0 ]; then
  die "stdin is not a terminal. This script is interactive by design — linking a repo to a deploy
       target is a human decision, not a pipeline step. Run it yourself in a terminal.
       To see what it would check without linking: $0 --dry-run"
fi

# We do NOT log you in. `vercel login` is an auth flow; a script that drives it is a script that
# handles your credentials, and this one has no business doing that.
# stdout ONLY. `vercel whoami` prints the username to stdout but a CLI banner to stderr; 2>&1
# folded the banner into VERCEL_USER, so "vercel user:" printed the banner instead of the name.
if ! VERCEL_USER="$(vercel whoami 2>/dev/null)" || [ -z "${VERCEL_USER}" ]; then
  die "you are not logged into the Vercel CLI (or it cannot reach Vercel).
       Log in yourself, then re-run:  vercel login"
fi
info "vercel user: ${VERCEL_USER}"

# ---------------------------------------------------------------- the default-branch invariant
# This is the check that keeps `dev` from becoming the production branch. Do it BEFORE linking, so
# a misconfigured repo never gets a Vercel project attached to it at all.
if ! DEFAULT_BRANCH="$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>&1)"; then
  die "cannot determine this repo's default branch (auth? network? no GitHub remote?): ${DEFAULT_BRANCH}
       Refusing to link: Vercel derives the PRODUCTION branch from the repository default branch,
       so if we cannot read it we cannot know what would deploy to production. A failure to verify
       is not a pass."
fi

if [ "${DEFAULT_BRANCH}" != "${PROD_BRANCH}" ]; then
  die "this repo's default branch is '${DEFAULT_BRANCH}', not '${PROD_BRANCH}'.

       REFUSING TO LINK. Vercel takes its production branch from the repository default branch.
       With '${DEFAULT_BRANCH}' as the default, every merge to '${DEFAULT_BRANCH}' would deploy
       straight to PRODUCTION — bypassing staging and inverting the branch flow, silently.

       Fix it, then re-run:
           gh repo edit --default-branch ${PROD_BRANCH}"
fi
info "default branch is '${DEFAULT_BRANCH}' — Vercel will take that as the production branch"

if [ "${DRY}" -eq 1 ]; then
  info "[dry-run] all pre-flight checks passed. Would now run: vercel link"
  info "[dry-run] nothing was linked, and nothing was deployed."
  exit 0
fi

# ----------------------------------------------------------------------------------- link
info "running 'vercel link' — pick the scope and project when prompted"
vercel link || die "vercel link failed or was cancelled — nothing was linked."

# vercel link writes ONE of two local formats, and which one is itself a signal:
#   .vercel/project.json  -> single-project format; carries projectId/orgId. This is what a PLAIN
#                            `vercel link` writes — CAPTURED LIVE 2026-07-15 against a real
#                            git-connected project, even after the CLI auto-connects the GitHub repo.
#                            Git-connection does NOT change the local file to repo.json.
#   .vercel/repo.json     -> multi-project format written by `vercel link --repo` (alpha). An earlier
#                            version of this script believed git-connection itself wrote repo.json; it
#                            does not — repo.json is a separate, explicit `--repo` choice. Its project
#                            id lives at .projects[].id (NOT .projectId), the team at .projects[].orgId.
#
# We read the id/orgId from whichever file is present. For repo.json we do so ONLY when it lists
# exactly one project — the single-app shape this template produces, whose schema is now captured. A
# repo.json with 0 or >1 projects has no single production branch to check, and picking one would be
# exactly the shape-guess this script exists to refuse, so those still get an HONEST refusal. (The old
# code refused EVERY repo.json, because its schema was uncaptured; now the single case is verifiable.)
if [ -f .vercel/project.json ]; then
  PROJECT_ID="$(jq -r '.projectId // empty' .vercel/project.json)"
  ORG_ID="$(jq -r '.orgId // empty' .vercel/project.json)"
  [ -n "${PROJECT_ID}" ] || die "could not read projectId from .vercel/project.json"
  info "linked to Vercel project ${PROJECT_ID}"
elif [ -f .vercel/repo.json ]; then
  PROJECT_COUNT="$(jq -r '.projects | length' .vercel/repo.json 2>/dev/null || echo 0)"
  if [ "${PROJECT_COUNT}" = "1" ]; then
    PROJECT_ID="$(jq -r '.projects[0].id // empty' .vercel/repo.json)"
    ORG_ID="$(jq -r '.projects[0].orgId // empty' .vercel/repo.json)"
    [ -n "${PROJECT_ID}" ] || die "could not read .projects[0].id from .vercel/repo.json"
    info "already connected (single-project .vercel/repo.json) — Vercel project ${PROJECT_ID}"
  else
    die "this repo is connected via the multi-project .vercel/repo.json format, which lists ${PROJECT_COUNT} Vercel projects, not exactly one.

       Re-running link is only handled here for a SINGLE-project repo.json (this template is a single
       app). With ${PROJECT_COUNT} projects there is no one production branch to check, and picking
       one would be a guess — the exact failure this script refuses to make. Verify by hand instead —
         Vercel dashboard -> Project -> Settings -> Environments -> Production -> Branch Tracking
       must say '${PROD_BRANCH}'.

       (Nothing is deploying: vercel.json still has deploymentEnabled: false.)"
  fi
else
  die "vercel link reported success but wrote neither .vercel/project.json nor .vercel/repo.json.
       Refusing to claim the repo is linked when it cannot be shown to be."
fi

# --------------------------------------------------------- verify what Vercel ACTUALLY thinks
# A project may carry an explicit productionBranch override, set by hand in the dashboard, and
# that override WINS over the repository default branch we verified above. So the gh check alone
# is not sufficient — we have to ask Vercel.
#
# THE CLI CANNOT ANSWER THIS. `vercel project inspect` has NO --json flag (checked against CLI
# 54.7.1; no vercel command does), and its human-readable output is not a contract worth parsing.
# An earlier version of this script called `vercel project inspect --json`, which the real CLI
# rejects as an unknown option — so the check silently returned nothing, fell through to a
# warning, and LINKED ANYWAY. It was verification theatre: it could never have caught anything.
# Its tests passed only because the stub implemented a flag that does not exist.
#
# So there are exactly two honest paths, and neither of them is "warn and carry on":
#
#   VERCEL_TOKEN set -> ask the documented REST API (GET /v9/projects/{id}) and REFUSE on a
#                       wrong answer. This is a real check.
#   no token         -> we CANNOT verify. Say so, and make a HUMAN confirm they have looked,
#                       because "I could not check" is not "it is fine". That is this repo's
#                       first rule, and the old code broke it.
VERCEL_API="https://api.vercel.com"
# PROJECT_ID and ORG_ID were read above from whichever local file `vercel link` wrote
# (.vercel/project.json, or a single-project .vercel/repo.json) — see that block.

# Verified against a live project (Vercel API, CLI 54.7.1): a git-connected project ALWAYS carries
# a populated `.link.productionBranch` — it is the branch itself ("main"), not an "override" that is
# absent when inherited. So an EMPTY value does not mean "inherits the default". It means `.link` is
# null: the project is NOT CONNECTED TO A GIT REPOSITORY AT ALL. Treating that as "verified" is the
# same warn-and-carry-on failure the --json bug had — it green-ticks an unknown. `vercel link` will
# happily create such a project (answer "no" to "Detected a repository. Connect it to this project?").
# So: no git link -> we have verified NOTHING -> refuse.
NO_GIT_LINK="__no_git_link__"

check_production_branch() { # echoes the branch, or NO_GIT_LINK; returns 1 if it cannot ask
  local url resp
  url="${VERCEL_API}/v9/projects/${PROJECT_ID}"
  [ -n "${ORG_ID}" ] && url="${url}?teamId=${ORG_ID}"
  resp="$(curl --fail -sS -H "Authorization: Bearer ${VERCEL_TOKEN}" "${url}" 2>/dev/null)" || return 1
  printf '%s' "${resp}" | jq -e . >/dev/null 2>&1 || return 1     # not JSON -> we did not get an answer
  if ! printf '%s' "${resp}" | jq -e '.link != null' >/dev/null 2>&1; then
    printf '%s' "${NO_GIT_LINK}"
    return 0
  fi
  printf '%s' "${resp}" | jq -r '.link.productionBranch // empty'
}

if [ -n "${VERCEL_TOKEN:-}" ]; then
  if ACTUAL="$(check_production_branch)"; then
    if [ "${ACTUAL}" = "${NO_GIT_LINK}" ]; then
      die "the Vercel project is not connected to any Git repository.

       REFUSING TO FINISH. Vercel reports no Git link for this project, so it has NO production
       branch to check — and nothing this script could verify. A project in this state deploys
       from CLI uploads, not from your branches, so the entire branch-flow guarantee is absent.

       This usually means 'vercel link' was answered with 'no' at:
           'Detected a repository. Connect it to this project?'

       Connect the repo (Vercel dashboard -> Project -> Settings -> Git), then re-run this script.

       (Nothing is deploying: vercel.json still has deploymentEnabled: false.)"
    elif [ -z "${ACTUAL}" ]; then
      die "Vercel reports a Git link for this project but no production branch.

       REFUSING TO FINISH. A failure to verify is not a verified pass. Every git-connected project
       observed carries a populated productionBranch, so this response is one we do not understand
       — and we will not green-tick what we cannot read. Check the project by hand:
           Vercel dashboard -> Project -> Settings -> Environments -> Production -> Branch Tracking"
    elif [ "${ACTUAL}" = "${PROD_BRANCH}" ]; then
      info "Vercel productionBranch is explicitly '${ACTUAL}'. Verified."
    else
      die "Vercel's production branch is '${ACTUAL}', not '${PROD_BRANCH}'.

       An explicit production-branch override is set in the Vercel dashboard, and it WINS over the
       repository default. Merges to '${ACTUAL}' would deploy to PRODUCTION.

       There is NO supported API to change this, so fix it by hand:
         Vercel dashboard -> Project -> Settings -> Environments -> Production -> Branch Tracking
       Set it to '${PROD_BRANCH}', then re-run this script to confirm."
    fi
  else
    die "VERCEL_TOKEN is set but the Vercel API would not answer (auth? network? rate limit?).

       Refusing to finish: a failure to verify is not a verified pass. Fix the cause, or unset
       VERCEL_TOKEN to take the manual-confirmation path instead."
  fi
else
  # No token: we genuinely cannot check. Do NOT print a green tick over an unknown, and do NOT
  # simply warn and exit 0 — a warning nobody actions is how an inert control ships. Make the human
  # look, and make them say so.
  #
  # TWO things must be confirmed, not one — and confirming only the branch is the bug this replaces.
  # The token path REFUSES a project with no Git connection (link:null): a project that deploys from
  # CLI uploads, not branches, where the branch-flow guarantee is absent and there is NO Branch
  # Tracking to read. Without a token we cannot detect that ourselves, so a human typing 'main' on
  # reflex would sail a NOT-CONNECTED project straight through a branch-only check and get a pass —
  # observed for real. So confirm the CONNECTION first; a project with no repo attached has nothing
  # to verify and must not pass.
  printf '\n'
  warn "CANNOT machine-verify this project (no VERCEL_TOKEN set, and the Vercel CLI emits no JSON)."
  warn "  Two things must be true, and only you can see them. Confirm BOTH, by hand."
  printf '\n'
  printf '  1. Open: Vercel dashboard -> Project -> Settings -> Git\n'
  printf '     This repository must be shown there as the CONNECTED Git repository.\n'
  printf 'Is it connected? [y/N] -> '
  IFS= read -r connected || connected=""
  case "${connected}" in
    y|Y|yes|YES) ;;
    *) die "no Git connection confirmed.

       If Settings -> Git shows no connected repository, this project deploys from CLI uploads, not
       from your branches — the branch-flow guarantee does not exist, and there is nothing here to
       verify. Connect the repo (or re-run 'vercel link' and answer YES to
       'Detected a repository. Connect it to this project?'), then re-run this script.

       (Nothing is deploying: vercel.json still has deploymentEnabled: false.)" ;;
  esac
  printf '\n'
  printf '  2. Open: Settings -> Environments -> Production -> Branch Tracking\n'
  printf 'Type the production branch it shows (anything else aborts) -> '
  IFS= read -r seen || seen=""
  if [ "${seen}" != "${PROD_BRANCH}" ]; then
    die "you entered '${seen:-<nothing>}', not '${PROD_BRANCH}'.

       The repo is LINKED but its production branch is not confirmed. Do NOT enable any deploys
       until Branch Tracking says '${PROD_BRANCH}' — otherwise merges to '${seen:-that branch}'
       would go straight to production. Fix it in the dashboard and re-run this script.

       (Nothing is deploying: vercel.json still has deploymentEnabled: false.)"
  fi
  info "connection and production branch ('${PROD_BRANCH}') confirmed by you (not machine-verified)"
fi

cat <<EOF

Linked. NOTHING IS DEPLOYING, and nothing will, until you say so.

vercel.json ships:   "git": { "deploymentEnabled": false }

To enable deploys, edit vercel.json and open a PR — that is the gate. Enabling a deploy is a
reviewed change to a tracked file, not a click. For this repo's branch flow that means:

    "git": {
      "deploymentEnabled": {
        "main": true,        # production
        "staging": true,     # pre-prod soak
        "dev": false         # integration branch — leave off unless you want a running preview
      }
    }

Anything you do NOT list defaults to TRUE in Vercel, so list every branch you care about.
EOF
