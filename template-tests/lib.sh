#!/usr/bin/env bash
# Shared assertions for the repo-template test scripts.
set -euo pipefail

FAILURES=0

pass() { printf '  ok   %s\n' "$1"; }
fail() { printf '  FAIL %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
# A skipped check is NOT a passed check, and must never read like one. It prints, loudly, so a
# suite that quietly stopped testing something cannot masquerade as a green run.
skip() { printf '  SKIP %s\n' "$1"; }

# Some assertions need real, authenticated access to the Avenue-Z org (apply-rulesets.sh reads the
# org PLAN before it does anything, and every decision hangs off that). A CI runner's GITHUB_TOKEN
# is repo-scoped and cannot read org details, so those blocks are skipped there rather than failing
# a run for a reason that has nothing to do with the change under test. Locally, with a real gh
# login, they run for real.
# An EXIT CODE IS NOT AN ANSWER. `gh api orgs/Avenue-Z -q .plan.name` exits 0 for a repo-scoped
# CI token and returns an EMPTY plan — the token can reach the org endpoint but cannot see its
# details. Checking only the exit status therefore reports "we have org access" when we do not,
# the guarded block runs, and apply-rulesets.sh correctly dies with "the plan came back empty".
#
# That is the exact failure apply-rulesets.sh itself was hardened against — laundering "I could
# not ask" into a value — and I reproduced it here in the guard meant to prevent it. So: demand a
# real, non-empty, non-null plan. Anything less is "I could not ask".
have_org_access() {
  local plan
  plan="$(gh api orgs/Avenue-Z -q .plan.name 2>/dev/null)" || return 1
  [ -n "${plan}" ] && [ "${plan}" != "null" ]
}

assert_eq() { # <expected> <actual> <msg>
  if [ "$1" = "$2" ]; then pass "$3"; else fail "$3 (expected '$1', got '$2')"; fi
}

# `A && pass "x" || fail "y"` is NOT if-then-else (shellcheck SC2015): `fail` also runs
# whenever `pass` itself returns non-zero. The assertions below are the honest form.
assert_match()   { if grep -qiE -- "$2" <<<"$3"; then pass "$1"; else fail "$1"; fi; }  # <msg> <regex> <text>
assert_nomatch() { if grep -qiE -- "$2" <<<"$3"; then fail "$1"; else pass "$1"; fi; }  # <msg> <regex> <text>
assert_file()    { if [ -f "$2" ]; then pass "$1"; else fail "$1"; fi; }                # <msg> <path>
assert_no_file() { if [ -f "$2" ]; then fail "$1"; else pass "$1"; fi; }                # <msg> <path>
assert_dir()     { if [ -d "$2" ]; then pass "$1"; else fail "$1"; fi; }                # <msg> <path>
assert_no_dir()  { if [ -d "$2" ]; then fail "$1"; else pass "$1"; fi; }                # <msg> <path>
assert_ok()      { local m="$1"; shift; if "$@"; then pass "$m"; else fail "$m"; fi; }  # <msg> <cmd...>

# git check-ignore exits 0 when the path IS ignored, 1 when it is not.
# --no-index is required: without it, git check-ignore consults the index,
# and a TRACKED file (e.g. .env.example) is always reported "not ignored"
# no matter what .gitignore says. That makes the assertion vacuous for any
# path that's already committed. --no-index forces pure pattern matching
# against .gitignore, which is what these assertions are meant to verify.
# Do not "simplify" this away.
assert_ignored() {
  if git check-ignore --no-index -q "$1"; then pass "$1 is ignored"; else fail "$1 should be ignored"; fi
}

assert_trackable() {
  if git check-ignore --no-index -q "$1"; then fail "$1 should be trackable but is ignored"; else pass "$1 is trackable"; fi
}

# Run a command attached to a REAL pty, feeding it stdin.
#
# scripts/apply-org-ruleset.sh refuses to apply unless stdin is a terminal — there is deliberately
# no --yes, no env var, and no piped-input path that reaches the apply. That is the point of it.
# But it means the apply path cannot be tested by piping into the script: the test has to give it
# an actual terminal, or it is only ever testing the refusal.
#
# `script` is the obvious tool and it does NOT work here: piping into it races the child, which
# sees EOF before it reaches its prompt and reads an empty line. So drive the pty directly and
# type only once the prompt has actually appeared — the same thing a human does.
pty_run() { # <stdin-text> <command-string>
  PTY_INPUT="$1" PTY_CMD="$2" python3 -c '
import os, pty, select, sys, time
cmd, inp = os.environ["PTY_CMD"], os.environ["PTY_INPUT"] + "\n"
pid, fd = pty.fork()
if pid == 0:
    os.execvp("bash", ["bash", "-c", cmd])
out, sent, deadline = bytearray(), False, time.time() + 30
while time.time() < deadline:
    if not select.select([fd], [], [], 0.2)[0]:
        continue
    try:
        data = os.read(fd, 4096)
    except OSError:
        break
    if not data:
        break
    out += data
    # Type only after the prompt is on screen. Sending sooner is the race above.
    if not sent and b"> " in bytes(out):
        os.write(fd, inp.encode())
        sent = True
os.close(fd)
_, status = os.waitpid(pid, 0)
sys.stdout.write(bytes(out).decode(errors="replace").replace("\r", ""))
# Propagate the child EXIT CODE. Without this, pty_run always looks like a success, and every
# "it refuses to X" assertion silently passes no matter what the script did.
sys.exit(os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1)
'
}

finish() {
  if [ "$FAILURES" -eq 0 ]; then printf '\nALL PASS\n'; exit 0; fi
  printf '\n%d FAILURE(S)\n' "$FAILURES"; exit 1
}
