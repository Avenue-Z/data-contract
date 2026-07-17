#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${REPO_ROOT}"
# shellcheck source=template-tests/lib.sh disable=SC1091
source template-tests/lib.sh

SCRIPT=./scripts/link-vercel.sh

# link-vercel.sh attaches a repo to a DEPLOY TARGET. Two things must hold, forever:
#
#   1. IT NEVER DEPLOYS. Not with a flag, not by accident, not as a "convenience".
#   2. IT NEVER LINKS A REPO WHOSE DEFAULT BRANCH IS NOT `main`.
#
#      Vercel takes its production branch from the repository default branch, and there is NO
#      documented API to set it otherwise. This template's default branch is `main` precisely so
#      that Vercel's default is correct. If someone flips it back to `dev`, then every merge to
#      `dev` deploys straight to PRODUCTION — bypassing staging, inverting the branch flow,
#      silently, with no error. This check is the only thing standing in front of that.
#
# Both are driven with stub `vercel` / `gh` on PATH, so no real API call is ever made.

assert_file "$SCRIPT exists" "$SCRIPT"
assert_ok   "$SCRIPT is executable" test -x "$SCRIPT"

STUB="$(mktemp -d)"
WORK="$(mktemp -d)"
trap 'rm -rf "${STUB}" "${WORK}"' EXIT

# Every stub call is logged, so we can prove what was and was not invoked.
export VERCEL_LOG="${STUB}/vercel-calls.log"

make_stubs() { # <default-branch> <production-branch-or-empty>
  local default_branch="$1" prod_branch="$2" inspect_json
  # Build the JSON in the PARENT and embed it whole. Interpolating a pre-quoted value inside the
  # heredoc produced `""dev""` -> `productionBranch:dev`, which is INVALID JSON: jq then returned
  # empty, the script read that as "no override" and exited 0, and the refusal test passed while
  # proving nothing. An invalid fixture is a silently vacuous test.
  # NOGIT models what the REAL API returns for a project with no Git connection: `"link": null`.
  # Verified against a live project — a git-connected project ALWAYS has a populated
  # productionBranch, so `link:null` (NOT a null productionBranch) is the only way the script can
  # see an empty value. The old fixture only ever produced `{"link":{"productionBranch":null}}`,
  # a shape the real API does not emit for a linked project, so the no-git case went untested and
  # the script green-ticked it as "no override — inherits the default branch. Verified."
  if [ "${prod_branch}" = "NOGIT" ]; then
    inspect_json='{"link":null}'
  elif [ "${prod_branch}" = "NOBRANCH" ]; then
    # Git-connected, but productionBranch is null — a shape we do not understand and must refuse
    # rather than green-tick. `.link != null`, so this is distinct from NOGIT.
    inspect_json='{"link":{"repo":"vercel-link-test","productionBranch":null}}'
  elif [ -n "${prod_branch}" ]; then
    inspect_json="{\"link\":{\"productionBranch\":\"${prod_branch}\"}}"
  else
    inspect_json='{"link":{"productionBranch":null}}'
  fi
  cat > "${STUB}/vercel" <<STUBEOF
#!/usr/bin/env bash
echo "vercel \$*" >> "${VERCEL_LOG}"
case "\$*" in
  whoami*)  echo "paul@avenuez.com" ;;
  link*)    mkdir -p .vercel; echo '{"projectId":"prj_test123","orgId":"team_test"}' > .vercel/project.json ;;
  deploy*)  echo "FAKE VERCEL: deploy was invoked!" >&2; exit 0 ;;
  *)        echo "fake vercel: unexpected: \$*" >&2; exit 1 ;;
esac
STUBEOF
  # The production-branch check goes over the REST API (the CLI cannot answer — no --json), so the
  # thing to stub is curl, not `vercel project inspect`.
  cat > "${STUB}/curl" <<STUBEOF
#!/usr/bin/env bash
echo "curl \$*" >> "${VERCEL_LOG}"
echo '${inspect_json}'
STUBEOF
  chmod +x "${STUB}/curl"
  cat > "${STUB}/gh" <<STUBEOF
#!/usr/bin/env bash
case "\$*" in
  *defaultBranchRef*) echo "${default_branch}" ;;
  *) echo "fake gh: unexpected: \$*" >&2; exit 1 ;;
esac
STUBEOF
  chmod +x "${STUB}/vercel" "${STUB}/gh"
}

# A minimal repo that looks like an initialised `next` stack.
setup_repo() { # <vercel.json contents>
  rm -rf "${WORK}/repo"; mkdir -p "${WORK}/repo/scripts"
  cp "${REPO_ROOT}/scripts/link-vercel.sh" "${WORK}/repo/scripts/"
  printf '%s\n' "$1" > "${WORK}/repo/vercel.json"
  : > "${VERCEL_LOG}"
}

deployed()  { grep -q '^vercel deploy' "${VERCEL_LOG}" 2>/dev/null; }
linked()    { grep -q '^vercel link'   "${VERCEL_LOG}" 2>/dev/null; }

# Model a `vercel link` that writes .vercel/repo.json — the multi-project format that
# `vercel link --repo` (alpha) produces, NOT what a plain git-connected `vercel link` writes.
# CAPTURED LIVE (2026-07-15) against a real git-connected Avenue-Z project: a normal
# `vercel link` — even after auto-connecting the GitHub repo — writes .vercel/project.json;
# `vercel link --repo` writes .vercel/repo.json, whose single-project shape is exactly:
#   {"remoteName":"origin","projects":[{"id":"prj_…","name":"…","directory":".","orgId":"team_…"}]}
# The project id lives at .projects[].id (NOT .projectId), and the team id at .projects[].orgId.
# <repo-json> is embedded whole (same lesson as make_stubs: build valid JSON in the parent).
link_writes_repojson() { # <repo-json-literal>
  local repo_json="$1"
  cat > "${STUB}/vercel" <<STUBEOF
#!/usr/bin/env bash
echo "vercel \$*" >> "${VERCEL_LOG}"
case "\$*" in
  whoami*)  echo "paul@avenuez.com" ;;
  link*)    mkdir -p .vercel; echo '${repo_json}' > .vercel/repo.json ;;
  deploy*)  echo "FAKE VERCEL: deploy was invoked!" >&2; exit 0 ;;
  *)        echo "fake vercel: unexpected: \$*" >&2; exit 1 ;;
esac
STUBEOF
  chmod +x "${STUB}/vercel"
}

# The single-project repo.json captured verbatim from the live CLI (ids swapped for the stub's,
# which the curl stub echoes back regardless of URL — but the URL is logged, so the tests below can
# prove the script pulled prj_test123 / team_test out of THIS file and put them in the API call).
REPO_JSON_ONE='{"remoteName":"origin","projects":[{"id":"prj_test123","name":"vercel-link-test2","directory":".","orgId":"team_test"}]}'
# A genuine monorepo: two projects. "Which one is production for this repo" is ambiguous -> refuse.
REPO_JSON_TWO='{"remoteName":"origin","projects":[{"id":"prj_web","name":"web","directory":"apps/web","orgId":"team_test"},{"id":"prj_api","name":"api","directory":"apps/api","orgId":"team_test"}]}'

# link-vercel.sh REQUIRES A TTY (linking a deploy target is a human act, not a pipeline step).
# So a plain `./link-vercel.sh </dev/null` dies at the TTY guard and never reaches the checks
# below — every "it refuses to X" assertion would then pass for the WRONG REASON, proving only
# that the TTY guard works. Run it over a real pty so the refusals are proven by the actual
# default-branch / deploys-off / production-branch checks.
run_linked() { # <branch-typed=main> <connection-answer=y> : no VERCEL_TOKEN, the manual-confirm path
  # The no-token path now asks TWO questions — first "is the Git repo connected?", then the branch.
  # Feed both as newline-separated stdin; the pty buffers them and the two `read`s consume in order.
  local typed="${1:-main}" conn="${2:-y}"
  out="$(pty_run "$(printf '%s\n%s' "${conn}" "${typed}")" "cd '${WORK}/repo' && PATH='${STUB}:'\"\$PATH\" VERCEL_LOG='${VERCEL_LOG}' ./scripts/link-vercel.sh")"
}

run_linked_token() { # -> sets $out. VERCEL_TOKEN set: the REST-API path, no human prompt.
  out="$(pty_run "" "cd '${WORK}/repo' && PATH='${STUB}:'\"\$PATH\" VERCEL_LOG='${VERCEL_LOG}' VERCEL_TOKEN=tok_test ./scripts/link-vercel.sh")"
}

DEPLOYS_OFF='{"git":{"deploymentEnabled":false}}'
DEPLOYS_ON='{"git":{"deploymentEnabled":true}}'
# The per-branch OBJECT form the success message tells operators to adopt to enable deploys.
DEPLOYS_PER_BRANCH='{"git":{"deploymentEnabled":{"main":true,"staging":true,"dev":false}}}'

# ---------------------------------------------------------------------------------------
# THE INVARIANT: this script must not contain a deploy at all. A guard in front of a `vercel
# deploy` that is still present in the file is one edit away from firing.
echo "link-vercel: the script must not invoke 'vercel deploy' ANYWHERE"
src="$(cat "$SCRIPT")"
if grep -qE '^[^#]*vercel +deploy' <<<"$src"; then
  fail "the script invokes 'vercel deploy' — linking must never deploy"
else
  pass "no 'vercel deploy' invocation anywhere in the script"
fi
assert_nomatch "no 'vercel --prod' either" '^[^#]*vercel .*--prod' "$src"

# ---------------------------------------------------------------------------------------
echo "link-vercel: happy path — links, verifies, and deploys NOTHING"
make_stubs "main" ""            # default=main, no production override => inherits main
setup_repo "$DEPLOYS_OFF"
if run_linked; then
  pass "links successfully when default branch is main and deploys are off"
else
  fail "happy path should exit 0. Output: ${out}"
fi
if linked;   then pass "it did run 'vercel link'"; else fail "it never linked"; fi
if deployed; then fail "IT DEPLOYED — linking must never deploy"; else pass "it did NOT deploy"; fi
assert_match "confirms deploys are off" 'NOTHING IS DEPLOYING' "$out"
assert_match "tells you how to enable a deploy (a PR)" 'open a PR' "$out"
assert_match "warns unlisted branches default to TRUE" 'defaults to TRUE' "$out"

# ---------------------------------------------------------------------------------------
# THE BIG ONE. If the default branch is `dev`, Vercel would make `dev` production.
echo "link-vercel: REFUSES to link when the default branch is not 'main' (dev would become production)"
make_stubs "dev" ""
setup_repo "$DEPLOYS_OFF"
if run_linked; then
  fail "linked a repo whose default branch is 'dev' — every merge to dev would deploy to PRODUCTION. Output: ${out}"
else
  pass "refuses to link when the default branch is 'dev' (non-zero exit)"
fi
out_dev="$out"
assert_match "says dev would deploy to production" 'straight to PRODUCTION' "$out_dev"
assert_match "tells you how to fix it" 'gh repo edit --default-branch main' "$out_dev"
if linked;   then fail "it linked anyway"; else pass "nothing was linked"; fi
if deployed; then fail "IT DEPLOYED";      else pass "nothing was deployed"; fi

# ---------------------------------------------------------------------------------------
echo "link-vercel: REFUSES when vercel.json does not disable deploys (linking would start them)"
make_stubs "main" ""
setup_repo "$DEPLOYS_ON"
if run_linked; then
  fail "linked with deploys enabled — this starts deploying on the next push. Output: ${out}"
else
  pass "refuses to link when vercel.json does not disable deployments"
fi
out_on="$out"
assert_match "explains unspecified branches are deployable" 'UNSPECIFIED branch as deployable' "$out_on"
if linked; then fail "it linked anyway"; else pass "nothing was linked"; fi

# ---------------------------------------------------------------------------------------
# The per-branch OBJECT form is a DELIBERATE, reviewed decision to enable deploys — the exact shape
# the success message tells operators to adopt. link-vercel links with deploys OFF as a gate, so it
# refuses a repo already past that gate, but HONESTLY: not with the missing/true-key message that
# implies an accidental runaway deploy, and it must change nothing. A raw grep for
# `"deploymentEnabled": false` could not tell this apart from a missing key — this is finding #1.
echo "link-vercel: HONESTLY refuses the per-branch object form (deploys already enabled on purpose)"
make_stubs "main" ""
setup_repo "$DEPLOYS_PER_BRANCH"
if run_linked; then
  fail "linked a repo that already enabled deploys per-branch. Output: ${out}"
else
  pass "refuses the object form"
fi
out_pb="$out"
assert_match   "recognizes the object form, not a missing key" 'already enables deploys per-branch' "$out_pb"
assert_nomatch "does not misdiagnose it as an accidental runaway deploy" 'UNSPECIFIED branch as deployable' "$out_pb"
if linked; then fail "it linked anyway"; else pass "nothing was linked"; fi

# ---------------------------------------------------------------------------------------
# An explicit dashboard override WINS over the repo default, so verifying the default is not
# enough. The CLI CANNOT report it (no vercel command has --json — see the contract test at the
# bottom), so the only real check is the documented REST API, behind VERCEL_TOKEN.
#
# The previous version of this script called `vercel project inspect --json`, which the real CLI
# REJECTS as an unknown option. It silently returned nothing, fell through to a warning, and linked
# anyway — a check that could never catch anything. These tests passed because the stub implemented
# a flag that does not exist. That is why the contract test below exists.
echo "link-vercel: with VERCEL_TOKEN — REFUSES a production-branch override that is not 'main'"
make_stubs "main" "dev"         # repo default is fine, but Vercel is overridden to dev
setup_repo "$DEPLOYS_OFF"
if run_linked_token; then
  fail "accepted a Vercel production-branch override of 'dev'. Output: ${out}"
else
  pass "refuses when Vercel's productionBranch override is 'dev'"
fi
out_ovr="$out"
assert_match "names the wrong branch" "production branch is 'dev'" "$out_ovr"
assert_match "says there is no API to fix it, so do it by hand" 'NO supported API' "$out_ovr"
assert_match "actually asked the REST API" 'api\.vercel\.com/v9/projects' "$(cat "${VERCEL_LOG}")"
if deployed; then fail "IT DEPLOYED"; else pass "nothing was deployed"; fi

# ---------------------------------------------------------------------------------------
# A project with NO GIT CONNECTION has `"link": null`, so `.link.productionBranch // empty` is
# EMPTY — the same empty the script used to read as "no override, inherits the default branch:
# Verified." It is not. It is a project with no repo attached, deploying from CLI uploads rather
# than from branches, where the branch-flow guarantee does not exist at all. `vercel link` creates
# exactly this if you answer "no" to "Detected a repository. Connect it to this project?" —
# observed against a real project, where the script printed "Verified." and exited 0.
echo "link-vercel: with VERCEL_TOKEN — REFUSES a project with no Git connection (link:null)"
make_stubs "main" "NOGIT"
setup_repo "$DEPLOYS_OFF"
if run_linked_token; then
  fail "green-ticked a project with NO Git connection — 'I could not check' is not 'it is fine'. Output: ${out}"
else
  pass "refuses a Vercel project that is not connected to a Git repository"
fi
assert_match "says the project has no git repo" 'not connected to any Git repository' "$out"
assert_nomatch "never claims it verified anything" 'Verified' "$out"
if deployed; then fail "IT DEPLOYED"; else pass "nothing was deployed"; fi

echo "link-vercel: with VERCEL_TOKEN — an override of exactly 'main' is accepted"
make_stubs "main" "main"
setup_repo "$DEPLOYS_OFF"
if run_linked_token; then
  pass "accepts an explicit productionBranch of 'main'"
else
  fail "should accept productionBranch=main. Output: ${out}"
fi
assert_match "reports it VERIFIED (machine-checked, not asserted)" "explicitly 'main'. Verified" "$out"

# ---------------------------------------------------------------------------------------
# A GIT-LINKED PROJECT WHOSE productionBranch IS null. `.link != null` (so it is not the NOGIT
# case), but `.link.productionBranch` is null — a shape no observed connected project produces.
# The script must REFUSE it rather than fall through to a green tick: "a failure to verify is not
# a verified pass". #29 added the die; this is the test #29 did not, so the branch can't silently rot.
echo "link-vercel: with VERCEL_TOKEN — REFUSES a Git-linked project whose productionBranch is null"
make_stubs "main" "NOBRANCH"
setup_repo "$DEPLOYS_OFF"
if run_linked_token; then
  fail "green-ticked a linked project with a null productionBranch — a shape it should not understand. Output: ${out}"
else
  pass "refuses a linked project with no readable production branch"
fi
assert_match "says there is a git link but no branch" 'Git link for this project but no production branch' "$out"
# NB: match the SUCCESS claim specifically, not the bare word "verified" — the refusal message
# legitimately contains "a failure to verify is not a verified pass".
assert_nomatch "never green-ticks it (no 'explicitly ... Verified')" "productionBranch is explicitly" "$out"
if deployed; then fail "IT DEPLOYED"; else pass "nothing was deployed"; fi

# ---------------------------------------------------------------------------------------
# NO TOKEN: we genuinely cannot check. The old code WARNED and exited 0 — an inert control. Now a
# human must confirm BOTH the Git connection AND the branch. "I could not check" is not "it's fine".
echo "link-vercel: without VERCEL_TOKEN — a human confirms the connection AND the branch"
make_stubs "main" ""
setup_repo "$DEPLOYS_OFF"
if run_linked "main" "y"; then   # connection: yes, branch: main
  pass "confirming the connection and typing 'main' completes the link"
else
  fail "connection=yes + branch=main should succeed. Output: ${out}"
fi
assert_match "admits it could not machine-verify" 'CANNOT machine-verify' "$out"
assert_match "makes the human confirm the connection" 'CONNECTED Git repository' "$out"
assert_match "says the confirmation is human, not machine" 'not machine-verified' "$out"

# THE ITEM-1 FIX. Without a token the script cannot see link:null, so a human who has NOT confirmed
# a connection must not be able to sail through on the branch alone. Answering 'n' to the
# connection question must abort BEFORE the branch is ever asked.
echo "link-vercel: without VERCEL_TOKEN — an unconfirmed Git connection ABORTS (before the branch)"
make_stubs "main" ""
setup_repo "$DEPLOYS_OFF"
if run_linked "main" "n"; then   # connection: NO — must abort even though branch would be 'main'
  fail "no connection confirmed, yet the script passed on a reflexive 'main' — the exact item-1 gap. Output: ${out}"
else
  pass "an unconfirmed Git connection is fatal, even when the typed branch is 'main'"
fi
assert_match "says no git connection was confirmed" 'no Git connection confirmed' "$out"
assert_nomatch "does not go on to claim confirmation" 'confirmed by you' "$out"
if deployed; then fail "IT DEPLOYED"; else pass "nothing was deployed"; fi

echo "link-vercel: without VERCEL_TOKEN — connection confirmed but branch is 'dev' ABORTS"
make_stubs "main" ""
setup_repo "$DEPLOYS_OFF"
if run_linked "dev" "y"; then    # connection: yes, branch: dev
  fail "the human said Branch Tracking shows 'dev' and the script exited 0 anyway. Output: ${out}"
else
  pass "a production branch of 'dev' reported by the human is fatal"
fi
assert_match "warns not to enable deploys" 'Do NOT enable any deploys' "$out"
assert_match "reassures nothing is deploying yet" 'deploymentEnabled: false' "$out"
if deployed; then fail "IT DEPLOYED"; else pass "nothing was deployed"; fi

# ---------------------------------------------------------------------------------------
# ITEM 2 — a repo.json that is NOT a single project must get an HONEST refusal, not a misleading
# crash. repo.json is the multi-project format written by `vercel link --repo` (alpha) — CAPTURED
# LIVE 2026-07-15: a plain git-connected `vercel link` writes project.json, so repo.json only shows
# up when someone used `--repo`. The old `[ -f .vercel/project.json ] || die "...project.json is
# missing"` aborted as if the CLI had failed — a path reachable from the script's OWN "re-run this
# script" advice. A repo.json with 0 (or >1) projects has no single project to check, so it is still
# refused; the single-project case is handled below. Model the not-single case with an empty array.
echo "link-vercel: a repo.json that is not a single project gets an honest refusal"
make_stubs "main" ""
setup_repo "$DEPLOYS_OFF"
link_writes_repojson '{"remoteName":"origin","projects":[]}'   # 0 projects -> nothing single to verify
if run_linked "main" "y"; then
  fail "a non-single-project repo.json did not refuse. Output: ${out}"
else
  pass "a repo.json with no single project is refused, not crashed-on"
fi
assert_match   "names the multi-project format honestly" 'multi-project .vercel/repo.json' "$out"
assert_nomatch "does NOT print the old misleading 'project.json is missing'" 'project.json is missing' "$out"
if deployed; then fail "IT DEPLOYED"; else pass "nothing was deployed"; fi

# ---------------------------------------------------------------------------------------
# THE UNLOCK. A SINGLE-project repo.json carries exactly the two fields the REST-API check needs —
# .projects[0].id and .projects[0].orgId (CAPTURED LIVE, see link_writes_repojson). So a re-run on
# an already-connected single-app repo can be VERIFIED for real, not honestly-refused. The old code
# refused every repo.json because its schema was uncaptured; now that it is captured, refusing a
# shape we CAN read would itself be the "failure to verify treated as..." — no, worse: a refusal to
# verify when we can. So: read the id from repo.json and ask the same documented REST API.
echo "link-vercel: with VERCEL_TOKEN — a single-project repo.json is VERIFIED via the REST API (main)"
make_stubs "main" "main"                 # curl stub -> {"link":{"productionBranch":"main"}}
setup_repo "$DEPLOYS_OFF"
link_writes_repojson "$REPO_JSON_ONE"
if run_linked_token; then
  pass "verifies a single-project repo.json instead of refusing it"
else
  fail "a single-project repo.json with productionBranch=main should verify and pass. Output: ${out}"
fi
assert_match "reports it VERIFIED (machine-checked, not asserted)" "explicitly 'main'. Verified" "$out"
# Prove it read the RIGHT fields out of repo.json: the id and orgId must appear in the API URL it built.
assert_match "used the project id from .projects[0].id" 'prj_test123' "$(cat "${VERCEL_LOG}")"
assert_match "used the orgId from .projects[0].orgId as teamId" 'teamId=team_test' "$(cat "${VERCEL_LOG}")"
assert_nomatch "does NOT fall back to the honest repo.json refusal" 'multi-project .vercel/repo.json' "$out"
if deployed; then fail "IT DEPLOYED"; else pass "nothing was deployed"; fi

echo "link-vercel: with VERCEL_TOKEN — a single-project repo.json with a 'dev' override is REFUSED"
make_stubs "main" "dev"                  # curl stub -> {"link":{"productionBranch":"dev"}}
setup_repo "$DEPLOYS_OFF"
link_writes_repojson "$REPO_JSON_ONE"
if run_linked_token; then
  fail "accepted a 'dev' production-branch override read from a single-project repo.json. Output: ${out}"
else
  pass "refuses a 'dev' override even when the id came from repo.json"
fi
assert_match "names the wrong branch" "production branch is 'dev'" "$out"
assert_match "actually asked the REST API" 'api\.vercel\.com/v9/projects' "$(cat "${VERCEL_LOG}")"
if deployed; then fail "IT DEPLOYED"; else pass "nothing was deployed"; fi

# ---------------------------------------------------------------------------------------
# The line we DO NOT cross: a genuine monorepo repo.json with >1 project. There is no single
# production branch to check, and picking one would be exactly the guess this whole script refuses
# to make. So a multi-project repo.json is still refused — honestly, naming the count.
echo "link-vercel: with VERCEL_TOKEN — a MULTI-project repo.json is still honestly refused (no guessing)"
make_stubs "main" "main"
setup_repo "$DEPLOYS_OFF"
link_writes_repojson "$REPO_JSON_TWO"
if run_linked_token; then
  fail "a multi-project repo.json was not refused — the script guessed which project is production. Output: ${out}"
else
  pass "a multi-project repo.json is refused rather than guessed"
fi
assert_match  "names how many projects it saw" '2 Vercel projects' "$out"
assert_nomatch "never green-ticks a multi-project repo.json" "explicitly 'main'. Verified" "$out"
if deployed; then fail "IT DEPLOYED"; else pass "nothing was deployed"; fi

# ---------------------------------------------------------------------------------------
# Without a token, a single-project repo.json must reach the SAME manual two-question path as
# project.json — not the honest refusal. The old code refused it before ever asking, so a
# legitimately-connected repo could not be confirmed at all without a token.
echo "link-vercel: without VERCEL_TOKEN — a single-project repo.json reaches the manual confirm path"
make_stubs "main" ""
setup_repo "$DEPLOYS_OFF"
link_writes_repojson "$REPO_JSON_ONE"
if run_linked "main" "y"; then           # connection: yes, branch: main
  pass "a single-project repo.json can be confirmed by hand and completes the link"
else
  fail "connection=yes + branch=main over a single-project repo.json should succeed. Output: ${out}"
fi
assert_match  "admits it could not machine-verify" 'CANNOT machine-verify' "$out"
assert_match  "confirms by the human, not the machine" 'confirmed by you' "$out"
assert_nomatch "does NOT honestly-refuse a single-project repo.json" 'multi-project .vercel/repo.json' "$out"
if deployed; then fail "IT DEPLOYED"; else pass "nothing was deployed"; fi

# ---------------------------------------------------------------------------------------
echo "link-vercel: --dry-run checks everything and links NOTHING"
make_stubs "main" ""
setup_repo "$DEPLOYS_OFF"
if out_dry=$(cd "${WORK}/repo" && PATH="${STUB}:${PATH}" VERCEL_LOG="${VERCEL_LOG}" ./scripts/link-vercel.sh --dry-run </dev/null 2>&1); then
  pass "--dry-run exits 0"
else
  fail "--dry-run should exit 0. Output: ${out_dry}"
fi
if linked;   then fail "--dry-run LINKED";   else pass "--dry-run linked nothing"; fi
if deployed; then fail "--dry-run DEPLOYED"; else pass "--dry-run deployed nothing"; fi

# ---------------------------------------------------------------------------------------
# CONTRACT TEST — does the REAL Vercel CLI actually support what this script invokes?
#
# THIS IS THE TEST THAT WAS MISSING, AND IT IS THE POINT OF THIS FILE.
#
# Every test above drives a STUB. A stub proves the script behaves correctly GIVEN ASSUMED CLI
# BEHAVIOUR — it cannot prove the assumption. The previous version of this script called
# `vercel project inspect --json`, a flag that DOES NOT EXIST. The real CLI rejects it, so the
# production-branch check silently returned nothing, fell through to a warning, and linked anyway:
# a control that could never once have fired. Every stub test passed, because the stub implemented
# the fiction.
#
# So: assert the script's assumptions against the CLI that is actually installed. Skipped (not
# failed) when the CLI is absent, so the suite still runs on a machine without it — but on any
# machine that HAS vercel, a drifted or invented flag fails here instead of in production.
echo "link-vercel: CONTRACT — the real Vercel CLI supports what the script invokes"
if ! command -v vercel >/dev/null 2>&1; then
  echo "  SKIP  the Vercel CLI is not installed — cannot check the script's assumptions against reality"
else
  # 1. Every `vercel <subcommand>` the script calls must exist.
  #    Detect by OUTPUT, not exit code: `vercel link --help` prints perfectly good help and then
  #    exits 2. An exit-code check would have failed a subcommand that plainly works. The banner
  #    line ("▲ vercel <sub>") only appears for a real subcommand — verified that a bogus one does
  #    not produce it, so this check discriminates rather than passing on everything.
  #    Capture FIRST, then match. `set -o pipefail` is on, and `vercel link --help` exits 2 while
  #    printing perfectly good help — piping it straight into grep makes the pipeline inherit that
  #    2 and the check fails on a subcommand that plainly works.
  for sub in whoami link; do
    help_out="$(vercel "$sub" --help 2>&1 || true)"
    if grep -q "vercel ${sub}" <<<"$help_out"; then
      pass "the real CLI has 'vercel $sub'"
    else
      fail "the script calls 'vercel $sub', but the installed CLI does not support it"
    fi
  done

  # 2. The script must NOT depend on a --json flag from any vercel command, because none has one.
  #    This is the exact assumption that was false. If a future Vercel adds --json, this test fails
  #    loudly and someone can simplify the script — which is the right way to find out.
  if grep -qE '^[^#]*vercel [a-z ]+--json' "$SCRIPT"; then
    fail "the script expects a vercel --json flag. No vercel command emits JSON — this is how the production-branch check silently became a no-op before."
  else
    pass "the script does not rely on a vercel --json flag (no vercel command has one)"
  fi

  # 3. Belt and braces: confirm the CLI really has no --json on the command someone would reach for.
  inspect_help="$(vercel project inspect --help 2>&1 || true)"
  if grep -q -- '--json' <<<"$inspect_help"; then
    fail "'vercel project inspect' NOW supports --json — the REST-API workaround in this script can be simplified, and this test should be updated"
  else
    pass "confirmed: 'vercel project inspect' still has no --json (the REST-API path is still required)"
  fi
fi

# ---------------------------------------------------------------------------------------
# SHAPE CONTRACT — assert the script handles the REAL response shapes, not the ones we assumed.
#
# The CLI-flag contract above is only half the lesson. The `--json` bug was an invented FLAG; the
# link:null bug was an invented response SHAPE — the stub emitted {"link":{"productionBranch":null}}
# for a not-connected project, but the real API (verified against a live project, 2026-07-15)
# returns {"link":null}. Both were fiction the stub made true. So pin the three shapes the live API
# actually produces, and assert the script has a distinct, non-green-tick branch for each:
#
#   {"link":null}                              -> no Git connection at all      -> REFUSE
#   {"link":{"productionBranch":null}}         -> connected, branch unreadable  -> REFUSE
#   {"link":{"productionBranch":"main"|"dev"}} -> connected, real branch        -> compare to main
#
# These are static presence checks, so they run even without the CLI: they stop a future refactor
# from collapsing the three shapes back into one and silently reviving the green-tick.
echo "link-vercel: SHAPE CONTRACT — the script handles all three real API response shapes"
shape_src="$(cat "$SCRIPT")"
assert_match "distinguishes link:null (no connection) — checks '.link != null'" '\.link != null' "$shape_src"
assert_match "refuses the no-connection shape"      'not connected to any Git repository' "$shape_src"
assert_match "refuses the connected-but-null-branch shape" 'Git link for this project but no production branch' "$shape_src"
assert_match "reads the branch only after ruling those out" 'link\.productionBranch' "$shape_src"
# The fictional shape must not be what the script keys 'inherits the default' off — that was the bug.
assert_nomatch "never treats an empty productionBranch as a verified pass" 'inherits the default branch.*Verified' "$shape_src"

# ---------------------------------------------------------------------------------------
# SHAPE CONTRACT (local files) — the two shapes `vercel link` writes, CAPTURED LIVE 2026-07-15
# against a real git-connected Avenue-Z project, NOT assumed:
#
#   .vercel/project.json  (plain `vercel link`, even after it auto-connects the GitHub repo):
#       {"projectId":"prj_…","orgId":"team_…","projectName":"…"}
#   .vercel/repo.json     (`vercel link --repo`, alpha multi-project mode):
#       {"remoteName":"origin","projects":[{"id":"prj_…","name":"…","directory":".","orgId":"team_…"}]}
#
# The earlier belief that git-connection itself writes repo.json was WRONG (it writes project.json);
# repo.json's project id is .projects[].id — NOT .projectId — and the team id is .projects[].orgId.
# Pin those field paths so a refactor cannot silently read the wrong key and re-earn a link:null-class
# bug, and pin that a not-single-project repo.json is refused rather than guessed.
echo "link-vercel: SHAPE CONTRACT — the script reads the captured repo.json fields, and only when single"
assert_match "reads the project id from repo.json at .projects[0].id (not .projectId)" 'projects\[0\]\.id' "$shape_src"
assert_match "reads the team id from repo.json at .projects[0].orgId"                   'projects\[0\]\.orgId' "$shape_src"
assert_match "only trusts a repo.json with exactly one project (guards the count)"      '\.projects | length' "$shape_src"
assert_match "still honestly refuses a non-single repo.json"          'multi-project .vercel/repo.json' "$shape_src"

finish
