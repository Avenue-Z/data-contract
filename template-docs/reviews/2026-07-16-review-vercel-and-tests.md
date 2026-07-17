# Review record: next-stack/Vercel + template-tests-in-CI diff (6f96b67..abbf600)

Documentation-only review record. No code changed. Findings verified by running the actual
scripts/tests, not just read. Ranked most-severe first; each is a follow-up, not fixed here.

## 1. `link-vercel.sh`'s deploy-off check contradicts its own instructions

`scripts/link-vercel.sh:77` (and the identical copy at `scripts/init-repo.sh:304`) greps for the
literal text `"deploymentEnabled": false`. But the script's own success message (line 322) tells
the operator to switch to a per-branch object form to turn deploys on:

    "deploymentEnabled": { "main": true, "staging": true, "dev": false }

Verified directly: that object form does not match the grep. So a developer who does exactly what
the script tells them to do — edit `vercel.json` to the object form, in a reviewed PR — makes every
later re-run of `link-vercel.sh` refuse with "REFUSING TO LINK" against a config that is correct.
The check is also duplicated in two files with no shared source of truth; a fix to one is easy to
miss in the other.

**Follow-up:** parse `.git.deploymentEnabled` with `jq` (already a hard dependency in both scripts)
instead of grepping raw text, and share the check between `init-repo.sh` and `link-vercel.sh`.

## 2. `test_apply_org_ruleset.sh` can crash before its most safety-critical assertion runs

Reproduced directly: `bash template-tests/test_apply_org_ruleset.sh` exits 127 partway through,
before ever reaching Defence 3 — the assertion that the script refuses a payload that would brick
every repo in the org.

Root cause: this diff correctly fixed `template-tests/lib.sh`'s `pty_run` to propagate the child's
real exit code (previously it always looked like success, silently laundering failures into
passes). But `test_apply_org_ruleset.sh:103,112,118` capture `pty_run`'s output as bare
`out=$(pty_run ...)` under `set -euo pipefail`, with no guard. Now that `pty_run` can legitimately
return non-zero, any environment where the wrapped command doesn't exec cleanly aborts the whole
file silently. (Triggered here by a `PATH` containing a space — e.g. macOS's default "Application
Support" entry — which corrupts the variable-assignment prefix passed to `bash -c` inside the pty.)
`test_link_vercel.sh`'s newer `pty_run` call sites are correctly wrapped in `if run_linked; then`;
these three were never updated to match.

**Follow-up:** guard the three `pty_run` call sites in `test_apply_org_ruleset.sh` the same way.

## 3. Front-door README dropped a safety caveat SECURITY.md says this repo was already burned by omitting

`README.md` (the template's new GitHub landing page) has zero occurrences of the caveat that
CODEOWNERS does not require approval (`required_approving_review_count: 0`). It's still present in
`README.repo.tmpl` (the generated-repo seed) at lines 68-69. `SECURITY.md` states plainly: "This
section used to claim CODEOWNERS did [force review], and that was false" — this is the same class
of doc drift recurring on the page most readers land on first.

**Follow-up:** restore the caveat to `README.md`.

## 4. Docs-cleanup pattern in `init-repo.sh` can delete a user's own file, not just the template's

`scripts/init-repo.sh:362`:

    find docs/superpowers/specs docs/superpowers/plans -maxdepth 1 -type f -name '*.md' \
      ! -name 'README.md' -delete

This matches by path and extension, not by authorship. If a team commits their own first design
spec into `docs/superpowers/specs/` before running `init-repo.sh` — a sequence the template's own
docs invite — it is silently deleted in the same commit as the template's cleanup. The prior
hardcoded-filename approach couldn't do this: a differently-named file would have survived.

**Follow-up:** match by the template's known filenames (as before), or move the template's own
design docs somewhere `init-repo.sh` can `rm -rf` wholesale (the same reasoning already applied to
`template-tests/` living outside `tests/`).

## 5. New required CI check has no behavioral test

`scripts/apply-rulesets.sh:97` conditionally requires the `template-tests` status check. The only
test coverage (`template-tests/test_rulesets.sh`) is a grep against the script's source text, not
an execution of `apply-rulesets.sh --dry-run` with an assertion on the resulting payload. A
regression in the file-gating condition (e.g. requiring it even when the workflow file is absent,
which would hang every PR in a generated repo pending forever) would ship undetected.

**Follow-up:** extend the live-org test block to assert on `required: template-tests` the same way
it already asserts on `required: ci`.

## Lower-priority (cleanup, not bugs)

- **`scripts/link-vercel.sh:56`** — reimplements the `warn`/`info`/`die` logging trio, now a 4th
  independent copy (alongside `init-repo.sh`, `apply-rulesets.sh`, `apply-org-ruleset.sh`) with no
  shared `scripts/lib.sh`. The four copies have already drifted (`init-repo.sh`'s `warn()` writes to
  stderr; `apply-rulesets.sh`'s does not, and prints `SKIP` not `WARN`).
- **`template-tests/test_next_stack.sh:29`** — `grep -A1 '^jobs:' "$CI" | tail -1 | grep -q '^  ci:$'`
  assumes the job key is the line immediately after `jobs:`. Passes today only because there's no
  comment between them; a future explanatory comment (the style used everywhere else in this repo)
  would false-fail a correctly-configured workflow.
