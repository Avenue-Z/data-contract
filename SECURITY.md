# Security

## Reporting

Email **paul.ramirez@avenuez.com**. Do not open a public issue.

## Never commit credentials

Service-account JSON, API keys, tokens, `.env.local` — none of it belongs in git.

`.gitignore` blocks the credential filenames we have thought of. That is a **denylist, and
denylists leak** — it is a convenience, not a control. The controls are:

| Control | Boundary |
|---|---|
| gitleaks pre-commit hook | Local, and **skippable with `--no-verify`** |
| `secret-scan` CI job | **Merge** — it fails the PR |

## The base-branch guard can be bypassed by a PR that edits the guard — ACCEPTED, NOT MITIGATED

`guard-base-branch` runs on `pull_request`, and GitHub Actions reads the workflow file **from the
PR's head**. The workflow checks out the base branch to get `scripts/check-base-branch.sh`, so a
PR cannot rewrite the *decision logic* it is judged by — but a PR that edits
`.github/workflows/guard-base-branch.yml` itself can still neuter the check.

**Nothing currently stops that. This section used to claim CODEOWNERS did, and that was false.**

`.github/rulesets/repo-ruleset.json` ships `required_approving_review_count: 0` and
`require_code_owner_review: false`. The zero is deliberate: an Avenue Z repo often has a single
maintainer, GitHub does not let anyone approve their own PR, and requiring an approval would make
the repo unmergeable by the only person working in it. `template-tests/test_rulesets.sh` pins both
values so they cannot drift apart quietly.

The consequence, stated plainly: **`.github/CODEOWNERS` forces nothing.** With code-owner review
not required and zero approvals required, CODEOWNERS only *auto-requests* a reviewer — the author
can merge without waiting for one. It is **routing, not enforcement**. `--team` on `init-repo.sh`
is still worth having for that routing (a change to the guard lands in the right queue) and the
script's insistence on a team with write access is still correct — a CODEOWNERS naming a team
without write is ignored outright, so it would not even route. But routing is all it buys.

So: **anyone with write access can neuter `guard-base-branch` in a PR and merge it unreviewed.**
The compensating factors are a small team, convention, and the fact that `secret-scan` is a
separate workflow the same PR would also have to disable. That is the whole of it.

**To actually close this**, a repo must require review: set `require_code_owner_review: true` and
`required_approving_review_count: 1` in `repo-ruleset.json` (and update the assertions in
`template-tests/test_rulesets.sh`, which exist to make this a conscious choice rather than an
accident). Every PR then needs a second human, including the maintainer's own. That is a per-repo
decision about team size. Make it deliberately — do not assume CODEOWNERS made it for you.

Note what this means: nothing stops the *push*. Private repos on the Free plan have no server-side
push protection. A credential can be committed, pushed to a branch, and reach the remote's object
store — where it survives even if the PR is closed unmerged.

**A key that reached the remote is burned. Rotate it.** Removing the commit is not sufficient.

## The SCA tier is only as current as the last person who set it — ACCEPTED, NOT MITIGATED

`.github/sca-policy.json` carries the dependency-scanning tier. Default `client-facing`: the `sca`
check blocks CI on High/Critical vulnerabilities **that have a fix**. `internal`: warns only. The file
is CODEOWNERS-guarded, so loosening it to `internal` routes the change to a code owner and surfaces it
in the PR — but, as the CODEOWNERS section above says, that is routing, not enforcement: it does not by
itself require approval, so a solo maintainer can still merge the downgrade themselves.

But exposure changes over a repo's life: an internal tool can grow a public surface. **The tier is
only as current as the last person who set it.** The template makes the setting visible and reviewed;
it cannot keep it *correct* as the product changes. Re-check the tier when a repo's exposure changes —
nothing else will.

Neither tier ever blocks on a finding with **no available fix**. That is deliberate: a new CVE against
an already-pinned dependency must not make every open PR unmergeable over something nobody can fix.
No-fix findings warn; Dependabot security updates (enabled at adoption) open the fix PR when one
exists, which is what turns the signal into an action.

### Bandit SAST: what it does and does not see (`python` stack)

The `python` stack's CI runs **Bandit**, which walks the Python **AST** for vulnerability *shapes* —
`shell=True`/`subprocess` injection, `yaml.load`, `pickle`, weak crypto, SQL built by string
concatenation, `assert` in production paths. On a `client-facing` repo a finding that is **both High
severity and High confidence** fails the required `ci` check; `internal` warns only. The tier is the
**same** `.github/sca-policy.json` dial the SCA gate reads.

Two boundaries, stated plainly:

1. **Bandit is AST-pattern analysis, not cross-file dataflow.** It flags shapes, not proven exploit
   paths, and it will both *miss* real dataflow bugs and *false-positive* on safe patterns. The
   High-confidence half of the block rule trims the false positives; it does not add dataflow.
2. **Bandit sees the `python` stack only.** The `node` and `next` stacks' first-party TypeScript is
   **unscanned** until CodeQL lands at the GitHub Team cutover (Item 4 Part B). This gap is named,
   not hidden — a failure to verify is not a verified pass.

**Suppression is a silent hole.** A `# nosec <TEST_ID>` (or a `[tool.bandit]` skip) is un-expiring
and, with no Security-tab dismissal trail on Free, the *only* control on it is code review of the
diff that adds it. Treat every new `# nosec` as a reviewed decision, not a convenience.
