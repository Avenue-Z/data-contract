# Hardening additions: SCA, supply-chain pins, test-runner integrity — design

**Date:** 2026-07-16
**Repo:** `Avenue-Z/repo-template`

## Problem

The template is fanatical about one class of risk — **secret leakage** — and largely silent on the
others. Two gaps stand out against the repo's own philosophy (*every control states what it does not
do; a failure to verify is not a verified pass*):

1. **No dependency-vulnerability coverage.** Secret leakage is real but relatively rare. A
   known-vulnerable dependency in a deployed, internet-facing service is the single most common
   real-world compromise path, and some repos generated from this template are actively
   client-facing products. Dependabot bumps versions on a schedule but nothing surfaces or acts on a
   *known CVE* in the tree.
2. **CI can pass without exercising the code.** The `ci` job goes green on one trivial smoke test.
   The runner-integrity guarantee ("tests actually ran") is implicit, not asserted.

Two further items are **not new gaps but hardening/decision work** already implied by the repo:
supply-chain pinning strength, and the still-open org-wide (Team-plan) questions.

This spec defines four additions and, as importantly, records where each one is genuinely solid
versus where it trades against an existing deliberate design. It is a **bundle spec**: items 1–3 are
implementable today; item 4 is research- and plan-gated and should get its own plan when the org
reaches GitHub Team.

---

## Item 1 — SCA (dependency-vulnerability scanning), tiered by exposure

**This is the substantive new feature and the highest-value item.** It was pressure-tested at length;
the design below is the version that survives, i.e. the one that does *not* become the enforcement
theater the template rejects.

### The finding, and why blocking is the hard part

An SCA scan resolves the full dependency tree (direct + transitive) and matches each
`package@version` against advisory databases (OSV / GitHub Advisory). A finding is *"this version is
known-vulnerable, fixed in X"* — it carries **no reachability guarantee** (it does not prove your code
calls the vulnerable path), so a large share of findings are inert transitive noise.

A naive blocking gate on the whole manifest reintroduces the exact pathology `secret-scan.yml` works
to avoid: the day a new CVE drops against an already-pinned dep, **every open PR fails** — including
PRs that never touched that dep — and the repo becomes unmergeable over something nobody can fix. So
the design is a *threshold*, not a binary, plus a hard invariant.

### Decision: two tiers + one invariant + auto-remediation

**Auto-remediation (both tiers):** turn on **Dependabot security updates**. This is a repository
*setting*, not a committed file, so it cannot live in `dependabot.yml` — it belongs in the adoption
playbook as a gated step (same class as `apply-rulesets.sh`). It makes findings arrive with a fix PR
already open rather than as a bare red mark, which is what closes the "nobody acts on the signal" gap
better than a scanner comment ever could.

**Two tiers, set by a committed, code-owned policy value:**

| Tier | Blocks on | Everything else |
|---|---|---|
| `client-facing` (default) | Critical / High **that have a fix** | warns |
| `internal` | nothing | warns |

**The invariant that holds across every tier:** *never block on a finding with no available fix.*
Severity floor AND fix-availability must both be true to block. This is what keeps a `client-facing`
repo from going unmergeable over an unpatched-upstream CVE, and it is the direct application of the
secret-scan scoping lesson.

**Governance (this is what stops the dial becoming a bypass):**

- **Fail-safe default.** The template ships `client-facing`. Downgrading to `internal` is the
  explicit act. Safe-by-neglect (an internal tool that becomes client-facing is still *strict*),
  never vulnerable-by-neglect.
- **Committed, code-owned policy file.** The tier lives in a version-controlled file that `.github/`
  CODEOWNERS guards — mirroring `vercel.json`'s `deploymentEnabled: false`. Loosening rigor requires
  a reviewed PR; it cannot be flipped silently under deadline pressure.
- **Two tiers, not three.** Three tiers is the severity matrix wearing a policy costume. Two is
  honest and memorable.

### Why tiering rescues the "small team = theater" objection

Blocking on *everything* produces a flood no small team can own, so the gate gets bypassed or
disabled. Blocking only on **High+/fixable, on the handful of repos that are `client-facing`**
collapses the volume to a few genuinely-actionable findings a year — small enough to actually own.
Tiering is the solution to the theater problem, not a compromise on it.

### Tooling

- **Today (private + Free):** `osv-scanner` in a workflow, reading the resolved tree, applying the
  tier's severity/fix threshold. Language-agnostic.
- **On Team (GitHub Advanced Security available):** swap to GitHub's `dependency-review-action` in
  *warn/block* mode per tier.

### Stated boundary (in the template's own idiom)

*The tier is only as current as the last person who set it. Exposure changes over a repo's life; the
template makes the setting visible and reviewed, it cannot keep it correct as the product changes.*
This goes in `SECURITY.md` alongside the merge-not-push boundary.

### Open decision for the plan

Exact file/shape of the committed policy value (a dedicated `.github/sca-policy.yml`, an input in the
SCA workflow, or a repo variable). The plan picks one; the design only requires that it be committed
and CODEOWNERS-guarded.

---

## Item 2 — Test-runner integrity guard

**Smaller than it first appears — recorded honestly.** Both runners already fail on zero tests by
default: `pytest` exits code 5 when it collects nothing, and `vitest run` fails when it finds no test
files (`passWithNoTests` defaults to `false`). So the "CI passes on zero tests" risk is *mostly*
already covered by defaults. The remaining, real hardening is to make that guarantee **explicit and
tamper-evident** rather than an accident of defaults:

- **Python:** add `--strict-config` and `--strict-markers` to the pytest invocation / config. These
  catch a mistyped config key or an unknown marker that would otherwise pass silently — the class of
  error that erodes the "tests ran and were configured as intended" guarantee.
- **Node / Next:** explicitly set `passWithNoTests: false` in the vitest config so a future config
  change cannot silently flip the zero-test behavior open.

Not a new CI step; a strictness tightening on the existing one. Coverage percentage is **explicitly
out of scope** (see Rejected).

---

## Item 3 — Supply-chain pin strength: SHA-pin GitHub Actions

**The most contentious of the four — it trades against a deliberate existing design.** Actions are
currently pinned to major-version *tags* (`actions/checkout@v7`), and `template-tests/test_action_pins.sh`
is a purpose-built lockstep harness around that choice (it keeps core and template workflows on the
same tag, because Dependabot is blind to `templates/`). The tag design is intentional and tested — not
an oversight.

**The security case for SHA-pinning:** a version tag is *mutable*. A compromised action maintainer
can repoint `v7` to malicious code, and every consumer picks it up on the next run — the 2025
`tj-actions/changed-files` compromise is exactly this. A commit SHA is immutable and closes that
vector. This is genuine defense-in-depth on top of the least-privilege tokens and injection-safe env
handling the template already has.

**The cost, stated plainly:**

- `test_action_pins.sh`'s pin regex (`@v?[0-9]...`) matches tags, not SHAs, and would need rewriting;
  its lockstep logic and the `@main/@master/@latest` float-guard must be preserved.
- SHA pins are less human-readable and harder to eyeball for lockstep drift — mitigated by the
  `# vX.Y.Z` comment convention and by Dependabot, which *does* bump SHA-pinned actions (updating both
  SHA and comment).

**This is a maintainer decision, not a mechanical fix.** SHA-or-nothing: there is no hash-verification
middle ground for actions the way there is for the checksum-verified gitleaks download. The plan
should treat "adopt SHA pinning" as a gated yes/no; if yes, it rewrites `test_action_pins.sh` to
assert SHA pins (7+ hex, with the version comment) instead of tags, across all core and template
workflows in lockstep.

---

## Item 4 — Team-cutover bundle (research- and plan-gated; do NOT implement now)

Sequenced with the org's move to GitHub Team, because none of it can run or be answered on private +
Free. Recorded here so it is not lost.

- **CodeQL SAST** (Python + TypeScript) — fills the static-analysis gap. Requires GitHub Advanced
  Security, so it cannot run on private + Free; it is part of the Team cutover, not a net-new
  Free-tier workflow.
- **Org-wide ruleset rollout** via the existing `apply-org-ruleset.sh`.
- **Resolve the two open questions already flagged in `docs/ADOPTION.md`**, both unanswerable until
  Team and both gating whether the org-wide + emergency-bypass design is even correct:
  1. Does a repo creator in `Avenue-Z` actually receive the **Admin** role on the repo they create?
  2. Does a repo-level **bypass actor survive an org-level ruleset**, or does the org ruleset outrank
     it?

This item is arguably the highest-leverage work overall because it is on the critical path the org is
already walking — but it is research first, implementation second, and gets its **own** spec/plan once
on Team. It is included in this document only to fix the sequencing.

---

## Sequencing

- **Now, no plan change:** Item 1 (osv-scanner + tiered policy + Dependabot-security-updates step),
  Item 2 (strict-flags tightening). Item 3 only if the maintainer decision is "yes".
- **On Team cutover:** Item 4, plus swap osv-scanner → `dependency-review-action`.

Items 1–2 (and 3, if approved) are a single implementation plan. Item 4 is deferred to its own plan.

## Testing

- **Item 1:** a `template-tests/` case asserting (a) the shipped default tier is `client-facing`
  (fail-safe), (b) the policy file/value is present and referenced by the SCA workflow, and (c) the
  never-block-without-a-fix invariant is encoded in the workflow's threshold logic, not just prose.
- **Item 2:** assert the pytest invocation carries `--strict-config`/`--strict-markers` and the
  vitest config sets `passWithNoTests: false`. Optionally a negative test: a stack with its tests
  removed must make `ci` go red, not green.
- **Item 3 (if adopted):** rewrite `test_action_pins.sh` to assert SHA pins + version comments in
  lockstep across core and templates; keep the float-ref guard.
- **Item 4:** out of scope here; its own plan.

## Rejected (pressure-tested out)

- **Coverage percentage / threshold gate** — gameable, noisy, and most misleading at exactly this
  scale (one function reads as 100% and only ever decays). Measure-don't-police still leaves an
  ignored number. The real theater risk is "zero tests ran," which Item 2 covers directly.
- **Integration / e2e test scaffolding** — speculative structure with no tests to house yet; violates
  the template's own YAGNI. A one-line convention note at most.
- **Playwright/E2E, SBOM, artifact signing, DAST, container scanning** — enterprise ceremony not
  warranted yet; only one stack even ships a container. Revisit if that changes.
- **Hard-blocking SCA on all findings / all repos** — reintroduces the unmergeable-repo pathology;
  see Item 1's invariant.

## Out of scope

- The `CLAUDE.md` seed skeleton and any `docs/` restructuring.
- Actual implementation — this is the design; the plan follows.
