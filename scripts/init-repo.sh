#!/usr/bin/env bash
#
# Turn a fresh copy of Avenue-Z/repo-template into a working repo.
#
#   ./scripts/init-repo.sh <python|node|next> [--team <slug>] [--no-push]
#
# --team <slug>: writes .github/CODEOWNERS naming @Avenue-Z/<slug>, after verifying the
#   team exists. If the team exists but lacks write access to the repo, the script GRANTS
#   it push (write) access rather than just warning — GitHub silently ignores a CODEOWNERS
#   entry for a team without write, so a warning nobody actions leaves the file inert.
#   Granting requires repo-admin or org-owner rights; if that fails the script dies rather
#   than write a CODEOWNERS that GitHub will ignore.
#
#   THIS IS A REAL PERMISSION CHANGE ON GITHUB. `--team` may add the team to the repo with
#   push access (PUT orgs/<org>/teams/<slug>/repos/<owner>/<repo>). It is documented here, in
#   README.md and in CONTRIBUTING.md. Omit --team and the script touches no permissions.
#
#   If this working copy has no GitHub remote yet, there is no repo to check write access
#   against: the file is still written, but the script warns LOUDLY that it may be inert.
#   Any OTHER failure to identify the repo (auth, network, rate limit) is fatal — a failure
#   to verify is never treated as a verified pass.
#
set -euo pipefail

ORG="Avenue-Z"
STACK=""
TEAM=""
PUSH=1

warn() { printf '\033[33mWARN\033[0m  %s\n' "$*" >&2; }
info() { printf '\033[32m--\033[0m    %s\n' "$*"; }
die()  { printf '\033[31mERROR\033[0m %s\n' "$*" >&2
         printf 'Recover with: git checkout -- . && git clean -fd\n' >&2
         exit 1; }

[ $# -ge 1 ] || die "usage: init-repo.sh <python|node|next> [--team <slug>] [--no-push]"
STACK="$1"; shift
case "${STACK}" in python|node|next) ;; *) die "stack must be 'python', 'node' or 'next', got '${STACK}'" ;; esac
while [ $# -gt 0 ]; do
  case "$1" in
    # An empty value is not the only bad value: `--team --no-push` would silently set
    # TEAM='--no-push' and then go looking for a team by that name. Anything starting
    # with '-' is a flag the user forgot to give a value to, not a slug.
    --team)    TEAM="${2:-}"
               [ -n "${TEAM}" ] || die "--team needs a slug"
               case "${TEAM}" in -*) die "--team needs a slug, got the flag '${TEAM}'" ;; esac
               shift 2 ;;
    --no-push) PUSH=0; shift ;;
    *)         die "unknown flag '$1'" ;;
  esac
done

git rev-parse --git-dir >/dev/null 2>&1 || die "not a git repository"

# HEAD MUST be dev. GitHub's "Use this template" gives you a single branch — main — so
# without this check the init commit lands on main, `dev` is never created, and the push
# dies with "src refspec dev does not match any" AFTER the commit. Worse, if dev exists
# but is not HEAD, dev is left stale — still carrying templates/ — and dev is the branch
# developers actually work on. Assert before we mutate anything.
HEAD_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
[ "${HEAD_BRANCH}" = dev ] || die "HEAD is '${HEAD_BRANCH:-detached}', not 'dev'. This script cuts staging and main from dev.
       Run: git checkout -b dev   (or: git checkout dev)   then re-run."

# NOTE: every function is defined BEFORE it is called. Bash executes a script
# sequentially — a call placed above its definition dies with "command not found".
# The idempotency short-circuit calls ensure_branches, so it lives at the bottom.

# ------------------------------------------------------------------ CODEOWNERS
# GitHub SILENTLY IGNORES a CODEOWNERS entry whose team does not exist or lacks
# write access. So we verify — granting write when it's missing — or we ship no
# file at all. Never enforcement theater.
#
# The guard below distinguishes "team is absent" (404 — an answer) from "I could not
# tell" (auth, network, rate limit — NOT an answer). set -e is disabled inside an
# `if` condition, so a bare `if ! gh api` would treat an expired token as a missing
# team and silently drop the control. That is the exact failure this file prevents.
resolve_codeowners() {
  if [ -z "${TEAM}" ]; then
    warn "no --team given — this repo will have NO code-owner review."
    rm -f .github/CODEOWNERS.tmpl
    return 0
  fi

  local out
  if out=$(gh api "orgs/${ORG}/teams/${TEAM}" 2>&1); then
    :   # exists
  elif grep -qE '"status": *"404"|HTTP 404|Not Found' <<<"${out}"; then
    warn "team '${TEAM}' does not exist in ${ORG} — dropping CODEOWNERS (no code-owner review)."
    rm -f .github/CODEOWNERS.tmpl
    return 0
  else
    die "cannot verify team '${TEAM}' (not a 404 — auth? network? rate limit?): ${out}"
  fi

  # Existence is necessary but NOT sufficient: the team must also hold write access
  # on THIS repo, or the CODEOWNERS entry is silently ignored just the same.
  #
  # The Accept header is REQUIRED. Without it this endpoint answers 204 No Content with an
  # EMPTY BODY, so `-q .permissions.push` yields "" — never "true" — and the check warns
  # "no WRITE access" for every team on earth, including the ones that have it. The
  # documented media type below returns a real JSON body: {"permissions":{"push":true,...},
  # "role_name":"write",...}. A check that cannot say yes is not a check.
  #
  # `gh repo view` has THREE outcomes and they are not interchangeable. The old code collapsed
  # them all into repo="" and then fell through and wrote CODEOWNERS anyway — so an expired
  # token or a network blip SKIPPED the write-access check entirely and shipped a CODEOWNERS
  # that GitHub may silently ignore. That is precisely the inert enforcement-theater file this
  # whole feature exists to prevent, and it fired on every run without a GitHub remote.
  #
  #   success            -> verify write access (and grant it) below.
  #   no GitHub remote   -> an ANSWER: there is no repo to check against yet. Write the file,
  #                         but say LOUDLY that write access is UNVERIFIED and the file may be
  #                         inert until someone checks. (Typical when init runs before the
  #                         first push.)
  #   any other failure  -> NOT an answer. Auth, network, rate limit. die.
  local repo perm repo_err
  local verified=0 unverified_reason=""
  if repo="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>&1)"; then
    :   # got the repo — fall through to the write-access check
  else
    repo_err="${repo}"
    repo=""
    if grep -qiE 'none of the git remotes|no git remotes|no remote|not a git repository|could not determine' <<<"${repo_err}"; then
      unverified_reason="this working copy has no GitHub remote yet"
    else
      die "cannot determine the target repo, and so cannot verify that @${ORG}/${TEAM} has write
       access to it (not a missing-remote — auth? network? rate limit?): ${repo_err}
       Refusing to guess: GitHub SILENTLY IGNORES a CODEOWNERS entry for a team without write
       access, so writing the file unverified would ship exactly the inert file this script
       exists to prevent. Fix the cause (gh auth status) and re-run."
    fi
  fi

  if [ -n "${repo}" ]; then
    verified=1
    if perm=$(gh api -H "Accept: application/vnd.github.v3.repository+json" \
                "orgs/${ORG}/teams/${TEAM}/repos/${repo}" -q '.permissions.push' 2>&1); then
      :   # got a real answer, true or false
    elif grep -qE '"status": *"404"|HTTP 404|Not Found' <<<"${perm}"; then
      # A 404 here is an ANSWER: the team is not attached to the repo at all — fold that
      # into "false" so the grant below fires for it exactly like an explicit non-write.
      perm=false
    else
      # Anything else (auth, network, rate limit) is NOT an answer. Do not guess.
      die "cannot check team write access (not a 404 — auth? network? rate limit?): ${perm}"
    fi

    if [ "${perm}" != "true" ]; then
      # A warning nobody actions leaves an inert CODEOWNERS — the exact silent-enforcement-
      # theater failure this file exists to prevent. Grant write instead of just naming the
      # problem. One PUT both attaches the team to the repo (if it wasn't) and sets push,
      # so it covers "not attached at all" and "attached with a lesser permission" alike.
      local grant
      if grant=$(gh api -X PUT "orgs/${ORG}/teams/${TEAM}/repos/${repo}" -f permission=push 2>&1); then
        info "granted @${ORG}/${TEAM} write access to ${repo}"
      elif grep -qE '"status": *"403"|HTTP 403|Forbidden' <<<"${grant}"; then
        die "cannot grant @${ORG}/${TEAM} write access to ${repo} (403 Forbidden) — you need repo-admin or org-owner rights on ${repo}. CODEOWNERS will be inert until someone with those rights grants the team write."
      else
        die "failed to grant @${ORG}/${TEAM} write access to ${repo} (not a 403 — auth? network? rate limit?): ${grant}"
      fi

      # Do not assume the PUT worked because it returned 0 — re-verify before writing
      # CODEOWNERS. If it still isn't true, die rather than ship an inert file.
      if perm=$(gh api -H "Accept: application/vnd.github.v3.repository+json" \
                  "orgs/${ORG}/teams/${TEAM}/repos/${repo}" -q '.permissions.push' 2>&1); then
        [ "${perm}" = "true" ] || die "granted write to @${ORG}/${TEAM} on ${repo} but re-verification still shows push=${perm:-unknown} — refusing to write CODEOWNERS"
      else
        die "cannot re-verify team write access after granting (not a 404 — auth? network? rate limit?): ${perm}"
      fi
    fi
  fi

  # Write the LIVE file — without the template's "TEMPLATE — not live" preamble, which
  # would otherwise sit as the first line of the file that IS live, contradicting itself.
  # The header states honestly WHAT WAS ACTUALLY VERIFIED, which is not the same in both paths.
  {
    if [ "${verified}" -eq 1 ]; then
      printf '# Code owners. Written by scripts/init-repo.sh after verifying that @%s/%s\n' "${ORG}" "${TEAM}"
      printf '# exists in the org AND holds write access to this repo.\n'
    else
      printf '# Code owners. Written by scripts/init-repo.sh, which verified that @%s/%s\n' "${ORG}" "${TEAM}"
      printf '# EXISTS in the org but could NOT verify it has write access to this repo\n'
      printf '# (%s).\n' "${unverified_reason}"
      printf '#\n'
      printf '# GitHub SILENTLY IGNORES a CODEOWNERS entry for a team without write access.\n'
      printf '# Until someone confirms @%s/%s has write here, this file may enforce NOTHING.\n' "${ORG}" "${TEAM}"
      printf '# Verify:  gh api orgs/%s/teams/%s/repos/<owner>/<repo> \\\n' "${ORG}" "${TEAM}"
      printf '#            -H "Accept: application/vnd.github.v3.repository+json" -q .permissions.push\n'
      printf '# Grant:   gh api -X PUT orgs/%s/teams/%s/repos/<owner>/<repo> -f permission=push\n' "${ORG}" "${TEAM}"
    fi
    sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' \
        -e "s|@${ORG}/TEAM_SLUG|@${ORG}/${TEAM}|" .github/CODEOWNERS.tmpl
  } > .github/CODEOWNERS
  rm -f .github/CODEOWNERS.tmpl

  if [ "${verified}" -eq 1 ]; then
    info "wrote .github/CODEOWNERS for @${ORG}/${TEAM} (write access verified on ${repo})"
  else
    warn ""
    warn "############################################################################"
    warn "# CODEOWNERS WRITTEN WITH UNVERIFIED WRITE ACCESS                          #"
    warn "############################################################################"
    warn "# ${unverified_reason}, so this script could NOT check"
    warn "# whether @${ORG}/${TEAM} has write access to this repo."
    warn "#"
    warn "# GitHub SILENTLY IGNORES a CODEOWNERS entry naming a team without write"
    warn "# access. No error, no warning — the file just enforces nothing."
    warn "#"
    warn "# .github/CODEOWNERS MAY BE INERT until you verify it. Re-running this script"
    warn "# will NOT fix it (a re-run repairs absence, not this). Once the repo is on"
    warn "# GitHub, check and if needed grant, by hand:"
    warn "#   gh api -X PUT orgs/${ORG}/teams/${TEAM}/repos/<owner>/<repo> -f permission=push"
    warn "############################################################################"
    warn ""
  fi
}

# -------------------------------------------------------------- branch lineage
# Cut staging and main from the POST-cleanup dev. Before the cleanup commit, dev
# still holds templates/ — branching early would leave all three heads carrying
# dead files forever. Create-if-absent; never force-push.
ensure_branches() {
  local head head_sha; head="$(git rev-parse --abbrev-ref HEAD)"; head_sha="$(git rev-parse HEAD)"
  for b in staging main; do
    if ! git rev-parse --verify -q "${b}" >/dev/null; then
      git branch "${b}" "${head}"
      info "created ${b} from ${head}"
    elif [ "$(git rev-parse "${b}")" = "${head_sha}" ]; then
      info "branch ${b} is already at ${head} — nothing to do"
    elif git merge-base --is-ancestor "${b}" "${head_sha}"; then
      # STRICTLY BEHIND — fast-forward it. This is not drift, and treating it as drift was a bug.
      #
      # On a FIRST run, `main` exists by construction: "Use this template" hands you a repo whose
      # only branch is main, so the documented path (`git checkout -b dev`) leaves a local main
      # sitting one commit behind dev. Refusing to touch it left main — the PRODUCTION branch, and
      # GitHub's default — pointing at the RAW UNINITIALIZED TEMPLATE: still carrying templates/,
      # template-tests/, and the template's own spec and plan. The script then printed "Done."
      # That defeats the entire reason this function runs after the cleanup commit rather than
      # before it (see the header above), and it did so silently.
      #
      # Fast-forwarding is safe precisely BECAUSE the branch is an ancestor of HEAD: no commit
      # that exists only on ${b} can be lost, because there is no such commit. A branch that has
      # genuinely diverged is a different animal and is left alone below.
      git branch -f "${b}" "${head_sha}"
      info "fast-forwarded ${b} to ${head} (it was behind — on a first run main still holds the uninitialized template)"
    else
      # DIVERGED — ${b} carries commits that ${head} does not. Fast-forwarding would discard them.
      # Re-run repairs absence, not drift: reconcile this with a PR, not with a force-push.
      warn "branch ${b} has DIVERGED from ${head} — leaving it alone."
      warn "  It holds commits ${head} does not, so this script will not move it (that would drop them)."
      warn "  Reconcile it by opening a PR, not by re-running this script."
    fi
  done
  if [ "${PUSH}" -eq 1 ]; then
    # Push only what exists. Naming a branch that isn't there aborts the whole push with
    # "src refspec X does not match any" — and pushes nothing at all, including the
    # branches that WERE fine.
    local existing=()
    for b in dev staging main; do
      if git rev-parse --verify -q "${b}" >/dev/null; then existing+=("${b}"); fi
    done
    [ "${#existing[@]}" -gt 0 ] || die "no dev/staging/main branch exists to push"
    git push -u origin "${existing[@]}"
    info "pushed ${existing[*]}"
  else
    info "--no-push: branches created locally only"
  fi
}

# ------------------------------------------------------------------------ main

# Idempotency short-circuit. Placed HERE, after ensure_branches is defined.
# Re-run repairs ABSENCE, not DRIFT: if templates/ is gone, the stack was selected on a
# previous run — do not re-copy, do not reset, do not force-push. A stale main is
# reconciled by opening a PR, not by re-running this script.
if [ ! -d templates ]; then
  info "templates/ already removed — this repo is initialized. Ensuring branches exist."
  ensure_branches
  exit 0
fi

info "initializing as a '${STACK}' repo"

[ -d "templates/${STACK}" ] || die "templates/${STACK} not found"

# 1. copy, 2. verify, 3. remove, 4. commit once, 5. push dev, 6. THEN branch.
cp -R "templates/${STACK}/." .
if [ "${STACK}" = python ]; then
  [ -f pyproject.toml ] || die "copy failed: pyproject.toml missing"
else
  [ -f package.json ] || die "copy failed: package.json missing"
fi
[ -f .github/workflows/ci.yml ] || die "copy failed: .github/workflows/ci.yml missing"

# vercel.json is a CONTROL, not a config file: it carries `deploymentEnabled: false`, and Vercel
# treats every UNSPECIFIED branch as deployable. So a missing vercel.json does not mean "no Vercel
# settings" — it means EVERY BRANCH DEPLOYS, including preview deploys off every feature branch,
# the moment someone links the project. A silent copy failure here would hand you the exact
# runaway-deploy behaviour the file exists to prevent. Absence is fatal.
if [ "${STACK}" = next ]; then
  [ -f vercel.json ] || die "copy failed: vercel.json missing.
       Refusing to continue: vercel.json is what keeps deploys OFF by default. Without it, Vercel
       treats every branch as deployable and linking the project would start deploying immediately."
  # Parse with jq (a hard dependency), not a raw grep: this verifies the CONTROL file the template
  # just copied is intact. Unlike link-vercel.sh's check, there is no per-branch object form to
  # accept here — at init time vercel.json is the freshly-copied template, which ships `false`.
  # Anything else means the copy is wrong, so require exactly `false` and fail closed otherwise.
  [ "$(jq -r '.git.deploymentEnabled' vercel.json 2>/dev/null)" = false ] \
    || die "vercel.json does not disable deployments. Refusing to continue: the template ships
       deploys OFF so that enabling one is a reviewed change, not an accident."
  info "vercel.json present — deploys are OFF until someone enables a branch in a PR"
fi
info "copied templates/${STACK} and verified"

resolve_codeowners

# Dependabot: the core declares only github-actions (the one ecosystem it actually has).
# Append the block for the stack we just selected, so this repo declares exactly what it has.
add_dependabot_ecosystem() {
  local eco
  # next is a node project — same ecosystem, different skeleton.
  case "${STACK}" in python) eco=pip ;; node|next) eco=npm ;; esac
  cat >> .github/dependabot.yml <<EOF
  - package-ecosystem: ${eco}
    directory: "/"
    schedule: { interval: weekly }
    target-branch: dev
    open-pull-requests-limit: 5
EOF
  info "added the '${eco}' ecosystem to .github/dependabot.yml"
}
add_dependabot_ecosystem

# Strip everything that is ABOUT the template rather than part of the generated repo. The
# spec promises a generated repo carries ZERO dead files.
#
#   templates/       — the unselected stack (and the selected one, now copied into place)
#   template-tests/  — the template's OWN bash suite. It must NOT ship: it tests the
#                      template's premises, two of which INVERT the moment ci.yml exists
#                      (test_rulesets.sh / test_apply_rulesets.sh assert "the core has no
#                      ci.yml"), so a generated repo would ship two tests that FAIL out of
#                      the box. It lives in template-tests/ — not tests/ — precisely so this
#                      one `rm -rf` removes it wholesale without touching the stack's own
#                      tests/ skeleton, which we just copied in.
#   template-docs/    — the template's OWN design docs (its specs and plans, ~500 lines about
#                      repo-template itself). They live OUTSIDE docs/superpowers/{specs,plans}/
#                      — the dirs the generated repo uses for ITS docs — precisely so this one
#                      `rm -rf` removes them wholesale WITHOUT touching a spec the adopter may
#                      have already written. Matching those dirs by pattern instead would delete
#                      the adopter's own first spec along with the template's. The empty
#                      docs/superpowers/{specs,plans}/ dirs and their README + .gitkeep stay:
#                      that is where the new repo's own specs and plans go. (New TEMPLATE design
#                      docs must be authored into template-docs/, not docs/superpowers/specs/ —
#                      test_init_repo.sh fails if a dated doc is left in the latter.)
#
# init-repo.sh does NOT delete itself: criterion 7 requires a re-run to be a no-op exiting 0,
# and a self-deleting script cannot be re-run. The re-run IS the recovery path for a first run
# that died partway. scripts/ keeps apply-rulesets.sh regardless.
rm -rf templates template-tests template-docs
# The workflow that RUNS that suite must go with it. If it stayed, a generated repo would ship a
# job that runs a directory we just deleted — and if `template-tests` were ever a required check
# there, it would never report and hang every PR PENDING FOREVER. That is why apply-rulesets.sh
# requires the context only when the workflow file is actually present.
rm -f .github/workflows/template-tests.yml
info "removed templates/, template-tests/, template-docs/ and the self-tests workflow"

# The front door is template-only. README.md is the TEMPLATE's GitHub landing page; the seed a
# generated repo starts from lives in README.repo.tmpl — a .tmpl suffix so GitHub renders the front
# door and not the seed, the same reason CODEOWNERS.tmpl is not named CODEOWNERS. Swap the seed in
# over the front door. Verify it is there first: a missing seed would otherwise leave the template's
# front-door README shipping into the generated repo silently — the exact cruft this strip prevents.
[ -f README.repo.tmpl ] || die "README.repo.tmpl missing — refusing to ship the template's front-door README into the generated repo"
mv -f README.repo.tmpl README.md
# docs/ADOPTION.md documents how to ADOPT the template; it is meaningless once you have, so it does
# not ship — treated like the template's own spec/plan above.
rm -f docs/ADOPTION.md
info "installed the generated repo's README (from README.repo.tmpl); removed the adoption playbook"

git add -A
git commit -q -m "chore: initialize ${STACK} repo from Avenue-Z/repo-template"
info "committed the initialized tree"

if [ "${PUSH}" -eq 1 ]; then
  git push -u origin "$(git rev-parse --abbrev-ref HEAD)"
fi
ensure_branches

cat <<EOF

Done. Next:
  1. pre-commit install
  2. Fill in the TODOs in README.md and CLAUDE.md
  3. ./scripts/apply-rulesets.sh          # adds 'ci' to required checks now that ci.yml exists
  4. Enable Dependabot security updates (a repo setting — turns 'sca' findings into fix PRs):
       REPO="\$(gh repo view --json nameWithOwner -q .nameWithOwner)"
       gh api -X PUT "repos/\${REPO}/vulnerability-alerts"
       gh api -X PUT "repos/\${REPO}/automated-security-fixes"
EOF
