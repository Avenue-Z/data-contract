# Adopting the Avenue-Z repo template

Three tracks: a **net-new** repo (ready today), an **existing** repo (a careful manual port), and
**org-wide** protection (needs a GitHub plan upgrade). Read the one you need.

The template's governing rule applies to adoption too: **a failure to verify is not a verified
pass.** Where a step cannot be checked by a script, it is called out as a human gate — do not skip it.

---

## 1. Net-new repo — ready today

The whole point of the template: one click plus one script.

1. **Create the repo.** On `Avenue-Z/repo-template`, click **Use this template** → new **private**
   repo. GitHub copies only the default branch (`main`).
2. **Initialize the stack.** Clone it, then:

       git checkout -b dev
       ./scripts/init-repo.sh <python|node|next> [--team <slug>]

   - Copies the chosen stack into place and deletes the others.
   - Strips the template's own machinery (`templates/`, `template-tests/`, its workflow and specs)
     so the new repo carries **zero** template cruft.
   - Commits once and pushes `dev`, `staging`, and `main`.
   - **Run it from `dev`.** The default branch is `main` on purpose — Vercel and most tooling take
     the *production* branch from the repository default, so defaulting to `dev` would deploy every
     merged PR straight to production. A fresh copy lands you on `main`, and the script refuses to
     run until you `git checkout -b dev`.
   - `--team <slug>` writes `.github/CODEOWNERS` **only** after verifying the team exists and has
     write access — granting write if it is missing. GitHub silently ignores a CODEOWNERS entry for
     a team without write, so the script grants it or ships no file at all. Omit `--team` and no
     permissions are touched. Note: CODEOWNERS **routes** reviewers; the ruleset ships
     `required_approving_review_count: 0`, so it does not by itself **require** approval.
3. **Apply protection.** `./scripts/apply-rulesets.sh` applies branch protection where the plan
   allows and prints exactly what it skipped. On a **private repo on the Free plan** it will tell
   you plainly that `main` is *not* protected and that enforcement is `guard-base-branch` +
   `secret-scan` + convention. That is expected, not a failure.
4. **`next` stack only — link Vercel.** `vercel login`, then `./scripts/link-vercel.sh`. It links but
   **never deploys**: `vercel.json` ships `deploymentEnabled: false`, and it refuses to link unless
   the default branch is `main`. Enabling a branch means editing `vercel.json` in a reviewed PR.
5. **Turn on dependency auto-remediation.** So a known-vulnerable dependency arrives as an open fix
   PR, not a bare red `sca` check, enable Dependabot alerts and security updates:

       REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
       gh api -X PUT "repos/${REPO}/vulnerability-alerts"
       gh api -X PUT "repos/${REPO}/automated-security-fixes"

   This is a repository **setting**, not a committed file — it cannot live in `dependabot.yml`, so it
   is a deliberate one-time step here (same class as `apply-rulesets.sh`). The `sca` check enforces
   the tier in `.github/sca-policy.json` (default `client-facing`: blocks CI on High/Critical vulns
   **that have a fix**); these settings make that fix show up automatically. Downgrading the tier to
   `internal` routes an edit to that CODEOWNERS-guarded file to a code owner and surfaces it in the PR
   (routing, not required approval) — see `SECURITY.md`.

6. **Fill in the skeleton.** Complete the `<!-- TODO -->` markers in `README.md` and `CLAUDE.md`, and
   install the local hook: `pre-commit install`.

**Claude Code skills (once per machine, not per repo):**

    /plugin marketplace add Avenue-Z/claude-marketplace
    /plugin install setup@avenue-z

`repo-template-first` also routes "new repo / scaffold a service" requests to this flow
automatically, so for net-new work adoption is essentially free once people know to start here.

---

## 2. Existing repo — a careful manual port

There is **no retrofit script, on purpose.** The design leaves existing repos untouched because the
obvious shortcut is dangerous: getting free branch protection means making the repo **public**, and
making a private repo public **exposes its entire git history**. Some existing repos have credentials
in their working trees or history. So the port is manual and gated on a secret audit.

**Do this in order:**

1. **Audit history for secrets first.** Before anything else, and before any thought of changing
   visibility:

       gitleaks detect --source . --log-opts="--all"

   **Rotate anything it finds.** Removing the commit is not enough — a key that reached the remote is
   burned. This step is non-negotiable and comes before the rest.
2. **Copy the stack-agnostic governance** (safe on a private repo, no visibility change needed):
   - `.github/workflows/guard-base-branch.yml` + `scripts/check-base-branch.sh`
   - `.github/workflows/secret-scan.yml`
   - `.pre-commit-config.yaml` (then `pre-commit install`)
   - the credential and env blocks from `.gitignore`, and `.env.example`
   - `CONTRIBUTING.md`, `SECURITY.md`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/dependabot.yml`
3. **Adopt the branch model.** Create `dev` and `staging`; set the default branch per the model
   (and to `main` if the repo deploys to Vercel — see the production-branch note above).
4. **Protection comes last, and only where possible.** Branch protection and rulesets are
   unavailable on private repos on Free. Until the repo is public or the org is on Team, enforcement
   is exactly what a new private repo gets: `guard-base-branch` + `secret-scan` + convention.
   **Do not flip a private repo to public** without completing step 1 and rotating any findings.

---

## 3. Org-wide protection — needs GitHub Team

`scripts/apply-org-ruleset.sh` applies one ruleset to **every** repo in `Avenue-Z` at once, so it is
deliberately hard to run: no `--yes`, no non-interactive path, a typed challenge phrase, and a
refusal to apply a payload that declares required status checks (which would hang every PR pending in
repos that lack those workflows). It requires the **GitHub Team** plan — org-level rulesets do not
exist on Free.

Before the org-wide rollout, two questions from the design are still **open** and must be confirmed
on Team first (both are unanswerable on Free):

1. Does a repo creator in `Avenue-Z` actually receive the **Admin** role on the repo they create?
2. Does a repo-level **bypass actor survive an org-level ruleset**, or does the org ruleset outrank it?

The answers determine whether the emergency-bypass design works and whether non-owners can manage
protection. Confirm them before either claim lands in `CONTRIBUTING.md`. Upgrading the org to Team is
a deliberate decision, not a step this template can take for you.
