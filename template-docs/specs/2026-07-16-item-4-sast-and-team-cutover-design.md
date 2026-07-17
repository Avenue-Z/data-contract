# Item 4 — first-party SAST + Team cutover — design

**Date:** 2026-07-16
**Repo:** `Avenue-Z/repo-template`
**Parent:** `2026-07-16-hardening-additions-sca-and-supply-chain-design.md` (Item 4)

## Why this is its own spec

The parent bundle spec deferred all of Item 4 to the GitHub Team cutover on a single premise:
*static analysis needs GitHub Advanced Security, which does not exist on private + Free.* That premise
is **half wrong**, and the error is worth correcting because it left first-party code unscanned
indefinitely.

**What is actually Team-gated is GitHub's private-repo Code Scanning *UI* — not static analysis
itself.** SAST-the-capability can run on private + Free the same way Item 1's SCA does: a plain
workflow that resolves findings and **fails the CI job**, with no Security tab in the loop. So Item 4
does not split cleanly along the Free/Team line. It splits along **capability + stack**:

| Piece | Gate | This spec |
|---|---|---|
| **A. Bandit SAST — `python` stack** | none — runs today on Free | design + implement now |
| **B. CodeQL cross-file SAST — Python + TS** | Team (GitHub Advanced Security) | design decisions recorded; deferred |
| **C. Org-ruleset rollout + the two open questions** | Team (org rulesets don't exist on Free) | research protocol; deferred |

Part A is the correction. Parts B and C remain genuinely Team-gated — Part C is the highest-leverage
work in the whole hardening effort, because its two open questions gate whether the org-wide +
emergency-bypass design is even correct.

---

## Part A — Bandit SAST for the `python` stack (implementable now)

**The osv-scanner pattern, applied to first-party code.** Bandit walks the Python AST for
vulnerability patterns — `shell=True`/`subprocess` injection, `yaml.load`, `pickle`, hardcoded
secrets, weak crypto, SQL built by string concatenation, `assert` in production paths. It runs as a
**`bandit` job in the `python` stack's existing `ci.yml`**, surfacing through the already-required
`ci` check on findings that clear the tier's threshold; no Security tab, no Advanced Security. (Why
the existing `ci` check and not a dedicated workflow is spelled out under *Wiring* below — it is the
lower-landmine design, not an open question.)

### Decision: reuse Item 1's tier selector; add confidence as a new, SAST-specific axis

Bandit emits a **severity** *and* a **confidence** level (each low/med/high) per finding. Part A
reuses Item 1's **tier selector** (`client-facing` blocks / `internal` warns) unchanged, but it does
**not** inherit Item 1's blocking *rule* — it introduces a second axis Item 1 does not have:

| Tier | Bandit blocks on | Everything else |
|---|---|---|
| `client-facing` (default) | **high severity AND high confidence** | warns |
| `internal` | nothing | warns |

Be honest about what this is. Item 1's invariant is *never block a finding with no available fix*
([`sca-gate.sh`](../../../scripts/sca-gate.sh) header) — an axis **orthogonal to severity**, about
whether a finding is *actionable*. Confidence is a different axis entirely: **false-positive
likelihood**. They share only a spirit ("don't block on noise"), so confidence is a **new dial Part A
adds**, justified on its own merits — pattern SAST false-positives where dataflow would not, and
gating on high-confidence-too collapses the volume to the handful a small team can actually own. It
is *not* a reuse of Item 1's fix-availability rule, and the Rejected section is worded to match.

### Self-contained, consistent with the template's posture

Bandit is Apache-2.0 (PyCQA), installs from PyPI, and makes **no network calls** — no token, no
registry, no cloud egress. That is why it, not Semgrep, is the right Free-tier tool here (see
Rejected). It fits the template's offline, no-external-service stance without qualification.

### Stated boundary (in the template's own idiom)

Two boundaries go in `SECURITY.md` alongside the merge-not-push and SCA-tier boundaries:

1. *Bandit is AST-pattern analysis, not cross-file dataflow. It flags shapes, not proven exploit
   paths, and it will both miss dataflow bugs and false-positive on safe patterns.*
2. *Bandit sees the `python` stack only. The `node` and `next` stacks' first-party TypeScript is
   **unscanned** until Part B (CodeQL) lands at the Team cutover.* This gap is named, not hidden —
   a failure to verify is not a verified pass.

Suppression is in-code `# nosec` (or a checked-in `[tool.bandit]` skip list). Named as a rot risk of
the same class as Item 1's boundary: a suppression is a silent, un-expiring hole, and without a
Security-tab dismissal trail the only control is code review of the diff that adds it.

### Wiring — decided by the template's own structure

Not an open question. **Bandit is a sibling `bandit` job in the `python` stack's `ci.yml`, and the
`ci` aggregate's gate step is extended to fail on it.** The template hands us the required `ci`
context to reuse; the load-bearing detail below is *how* Bandit's result reaches it, because the
obvious wiring silently doesn't block.

**The footgun: `needs` does not gate here.** `ci` is a bare aggregate with `if: always()`, and it
blocks the merge only through one hand-rolled step that inspects `needs.test.result`
([`ci.yml`](../../../templates/python/.github/workflows/ci.yml) lines 44-51). `if: always()`
deliberately decouples the job from `needs` failure — so adding `bandit` to `needs: [test, bandit]`
and stopping there ships **non-blocking SAST**: the `bandit` job goes red, but `bandit` is not a
required context (only `ci` is), and the required `ci` check stays green because its gate step never
looks at `needs.bandit.result`. Red check, green gate, PR merges — the exact theater this spec
exists to kill. So the plan **must** extend the `ci` gate step to also `exit 1` on
`needs.bandit.result != "success"`, mirroring the existing `test` check. (A Bandit *step* inside the
`ci` job would also work, but that job is intentionally a bare result-gate with no
checkout/setup-python; bolting a toolchain onto it is uglier than a sibling job + a two-line gate
extension.)

Why this home at all — it is the lower-landmine design:

- Every generated stack repo already ships a `ci.yml` with a required `ci` context.
  [`apply-rulesets.sh`](../../../scripts/apply-rulesets.sh) injects `ci` **only when
  `.github/workflows/ci.yml` exists** (lines 74/97), and [`init-repo.sh`](../../../scripts/init-repo.sh)
  copies that file per stack (presence asserted at line 293). The *core* `repo-template` has no
  `ci.yml`, which is exactly why `template-tests/test_rulesets.sh:26-30` forbids `ci` in the
  **committed core** rulesets — that assertion is about the core repo, **not** generated repos, which
  do have a `ci` job.
- Because `ci.yml` is **stack-scoped** (only `templates/python/` ships the Bandit-carrying one),
  `node`/`next` repos never contain the `bandit` job at all. No new required context, nothing for
  `init-repo.sh` to strip, and no PENDING-FOREVER risk — the pathology `sca.yml:16-19` warns about
  bites only a *new required context that some stacks can't report*. Reusing the existing `ci`
  context sidesteps it entirely.
- A **dedicated `bandit` workflow** (the `sca.yml` shape) is the *worse* choice here. `sca` gets away
  with a baked context because it is stack-**universal** (every stack has dependencies, so `sca`
  always reports). A python-only `bandit` context would instead have to be conditionally injected per
  stack and stripped for `node`/`next` — reintroducing precisely the hang that `ci.yml`'s
  stack-scoping avoids. The osv/sca precedent does not transfer, because Bandit's scope does not
  match sca's.

### Open decisions for the plan

- **Policy-file name.** Part A reads Item 1's tier from `.github/sca-policy.json` — a file named for
  SCA now also driving a SAST gate reads as a mistake to the next person. Decide *with* Item 1:
  rename to a stack-neutral `.github/security-policy.json` (a coordinated change that touches Item 1),
  or keep the shared file and comment the reuse at both call sites. Pick one; do not leave it
  implicit.
- Config location: `pyproject.toml` `[tool.bandit]` vs. a `.bandit` file — follow whatever the
  `python` stack already uses for tool config.
- The plan **must** confirm Item 1's policy value exists and is the exact key Part A reads (see
  Dependencies).

---

## Part B — CodeQL cross-file SAST (deferred to Team)

CodeQL is the **depth upgrade**, not a competitor to Part A: it does cross-file / cross-function
taint analysis for **Python *and* TypeScript**, which closes Part A's stated `node`/`next` gap and
adds real dataflow to the Python stack. It requires GitHub Advanced Security, so it cannot run on
private + Free and is part of the Team cutover.

Recorded so it is not re-litigated later; **not resolved here, and no dormant workflow is committed**
(a no-op file that ships now and silently does nothing is exactly the enforcement theater the parent
doc rejects):

- **Default setup vs. committed advanced workflow.** Default setup is one toggle and auto-updates;
  an advanced `codeql-analysis.yml` is version-controlled and CODEOWNERS-guardable but must be
  SHA-pinned and lockstepped like every other action (Item 3). Lean advanced, to keep the control
  committed and reviewed — confirm at cutover.
- **Warn vs. block per tier.** Mirror Item 1 / Part A: `client-facing` blocks on high, `internal`
  warns. CodeQL severity maps to the same committed policy value.
- **Relationship to Part A.** Once CodeQL covers Python, decide whether Bandit stays as a fast
  pre-Team gate or is retired to avoid double-reporting. Default: keep Bandit (it is free, local, and
  faster); dedupe noise via tier discipline.

---

## Part C — Org-cutover research protocol (the spine; Team-gated)

The two questions carried open since the org-ruleset design
([`docs/ADOPTION.md`](../../ADOPTION.md) §3) are **unanswerable on Free and gate correctness, not
polish** — they decide whether the emergency-bypass story in `CONTRIBUTING.md` is true or fiction. So
this part is a **research protocol, run first, on Team**: for each question, the exact probe, both
possible answers, and what each answer *forces*. It is deliberately not an implementation plan —
there is nothing correct to implement until these return.

### Q1 — Does a repo creator in `Avenue-Z` receive the **Admin** role on the repo they create?

This decides who can run [`apply-rulesets.sh`](../../../scripts/apply-rulesets.sh) — repo-level
protection requires admin on the repo.

**Probe (on Team, as a non-owner org member):**

```
# 1. A plain member creates a repo (or is given one created via the template).
# 2. Query that member's own permission on it:
gh api repos/Avenue-Z/<test-repo>/collaborators/<creator-login>/permission -q .permission
# expect: "admin" | "write" | "read" | "none"
# NB: -q .permission collapses to these four — a maintainer surfaces as "write", not "maintain".
# The table only hinges on admin-vs-not, which this distinguishes; if you need the granular role,
# query .role_name instead.
```

| Answer | What it forces |
|---|---|
| **`admin`** | Repo creators self-serve protection. `apply-rulesets.sh` works for any member on repos they create; `CONTRIBUTING.md` can state "you own protection on repos you create." Adoption playbook unchanged. |
| **anything but `admin`** (`write`/`read`/`none`) | Non-owner creators **cannot** apply repo rulesets. `apply-rulesets.sh` must be run by an org owner (or protection comes only from the org ruleset). The adoption playbook and `CONTRIBUTING.md` must reassign that step to an owner — a real change to the net-new flow in `ADOPTION.md §1`. |

### Q2 — Does a repo-level **bypass actor survive an org-level ruleset**, or does the org ruleset outrank it?

This decides whether an emergency break-glass at the repo level even functions once the org ruleset
(`enforcement=active`, `bypass_actors=[]`) is live. The likely answer from GitHub's layering
semantics is *org outranks* — rulesets are additive and the most-restrictive wins, each ruleset's
bypass list applying only to itself — but it **must be confirmed empirically**, because being wrong
here means either a break-glass that silently doesn't work or a false claim of one.

**Probe (on Team):**

```
# 1. Apply the org ruleset (bypass_actors=[]) via scripts/apply-org-ruleset.sh.
# 2. On a test repo, add a REPO ruleset that names an admin as a bypass actor.
# 3. As that admin, attempt a direct push to a protected branch:
git push origin HEAD:main    # on the test repo
```

| Answer | What it forces |
|---|---|
| **push blocked → org outranks; repo bypass does NOT survive** | There is **no repo-level break-glass** while the org ruleset is active. Emergencies require editing/disabling the *org* ruleset — the highest-blast-radius action in the repo. `CONTRIBUTING.md`'s emergency procedure must say so loudly, and the org ruleset itself becomes the single break-glass surface. |
| **push succeeds → repo bypass survives** | Repo owners can define a working per-repo break-glass actor even under the org ruleset. Document the pattern; the emergency-bypass design as sketched is viable. |

### Rollout mechanics (already built; runs after Q1/Q2 answer)

The org rollout tool exists and is deliberately hard to run:
[`scripts/apply-org-ruleset.sh`](../../../scripts/apply-org-ruleset.sh) (typed live-count challenge,
no `--yes`, refuses a required-status-check payload). Part C adds **no new tooling** — it gates the
*run* of that script on Q1/Q2 landing, and folds their answers into `CONTRIBUTING.md` before the
first org-wide apply.

### SCA tooling swap (Team)

Per the parent doc's sequencing: on Team, swap Item 1's `osv-scanner` for GitHub's
`dependency-review-action` in warn/block mode per tier. Same tier policy value, better native
integration. Recorded here to keep the cutover checklist in one place; no design change.

---

## Dependencies

- **Part A reads Item 1's policy value.** Item 1's implementation — `.github/workflows/sca.yml`,
  [`scripts/sca-gate.sh`](../../../scripts/sca-gate.sh), and the committed, CODEOWNERS-guarded tier
  file `.github/sca-policy.json` — lives on **`feat/sca-dependency-scanning`** and is **not yet on
  `dev`**; Part A cannot merge ahead of it, and its plan must confirm the exact key it reads.
  (The parent *design doc* is on `docs/sca-and-hardening-additions`, but the *files* Part A depends
  on are on `feat/sca-dependency-scanning` — depend on the branch that actually carries them.)
- Parts B and C depend only on the org reaching GitHub Team.

## Sequencing

- **Now (Free):** Part A (Bandit on the `python` stack), after Item 1 merges.
- **At Team cutover:** Part C research protocol **first** (Q1, Q2), then `CONTRIBUTING.md` updates,
  then the org-ruleset apply, then Part B (CodeQL) and the osv → `dependency-review-action` swap.

Part A is a small standalone plan (or folds into Item 1's plan). Parts B + C are a single Team-cutover
plan, gated on the research protocol.

## Testing

- **Part A:** a `template-tests/` case asserting (a) the Bandit gate ships with the `client-facing`
  default (fail-safe), (b) it reads its **tier** from Item 1's committed policy file (not a second
  *tier* dial — the confidence axis is a finding-filter inside the tier, not a new tier), (c) the
  block threshold is **high-severity-AND-high-confidence**, encoded in the workflow logic, not just
  prose, (d) **the `node` and `next` stacks contain no `bandit` job while their `ci` context still
  reports** — the node/next no-hang property, asserted so a later refactor to a dedicated workflow
  cannot silently reintroduce a pending-forever context, and **(e) — required, not optional —** a
  `python` stack with a seeded high/high finding must turn the **`ci` context itself** red on
  `client-facing` and green on `internal`. (e) is the only assertion that distinguishes "the gate
  blocks the required `ci` check" from "the gate reddens a non-required `bandit` check and merges
  anyway" — it is what catches the `needs`-doesn't-gate footgun in *Wiring*, so it must exercise
  `ci` specifically, not merely "the workflow."
- **Parts B & C:** out of scope for CI tests — B is Team-gated config and C is research whose output
  is decisions and `CONTRIBUTING.md` prose. Their verification is the probe results themselves.

## Rejected (pressure-tested out)

- **Semgrep OSS instead of Bandit** — its cross-file/cross-function taint (the part that would beat
  Bandit) is **paywalled** in Semgrep's Pro tier, so on OSS you get single-file pattern matching, the
  same class Bandit gives — while adding a registry/network dependency (`registry.semgrep.dev`, an
  optional `SEMGREP_APP_TOKEN` with findings egress to their cloud) and a larger third-party
  supply-chain surface to SHA-pin. Trading GitHub's paywall for Semgrep's, at a higher integration
  and egress cost, for no depth gain on Free. Bandit is free, local, and offline. Revisit Semgrep
  only if it replaces CodeQL for TS coverage before the org reaches Team.
- **A dormant/no-op CodeQL workflow committed now** — ships non-functional config that reads as
  coverage and does nothing; the exact theater the parent doc rejects. CodeQL lands at Team, live.
- **A separate SAST policy *tier*** — a third level or a Bandit-specific tier is the severity matrix
  in a policy costume. Part A reuses Item 1's two tiers verbatim. (It *does* add a confidence axis
  *within* those tiers — see the Decision above — but that is a finding-filter, not a new tier, and
  it is labeled as the new axis it is, not smuggled in as inheritance.)
- **Attempting Part C now on Free** — the probes cannot return a valid answer without Team; running
  them on Free would launder "could not ask" into a false "it works," the precise failure
  `apply-org-ruleset.sh` was written to refuse.

## Out of scope

- CodeQL implementation and the org-wide apply (both Team-gated; their own plan).
- Any change to Items 1–3.
