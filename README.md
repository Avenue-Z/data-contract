# <!-- TODO: repo-name -->

<!-- TODO: one sentence. What is this and who is it for? -->

## Stack
<!-- TODO -->

## Setup

    git clone git@github.com:Avenue-Z/<repo>.git && cd <repo>
    cp .env.example .env.local            # then fill it in
    <!-- TODO: install command -->
    pipx install pre-commit               # or: brew install pre-commit
    pre-commit install                    # installs the gitleaks hook

Avenue Z Claude Code skills (once per machine, not per repo):

    /plugin marketplace add Avenue-Z/claude-marketplace
    /plugin install setup@avenue-z

`setup` then auto-installs every Avenue Z plugin at **user scope**, so they work in all your repos
and keep themselves up to date. It is deliberately NOT wired into `scripts/init-repo.sh`: plugins
are a per-developer, per-machine concern, and init-repo runs once, for one person, on the day the
repo is created — it would do nothing for whoever clones this next month. (`.claude/` is gitignored
for the same reason: shared agent config lives in the marketplace, not in product repos.)

`pre-commit` is installed standalone rather than as a project dependency so the same line works
on both stacks. (The Python template also ships it in its `dev` extras, so
`pip install -e ".[dev]"` gets you it for free.)

## Run
<!-- TODO -->

## Tests
<!-- TODO -->

## Deploy
<!-- TODO -->

## Docs

- `docs/superpowers/specs/` — design specs
- `docs/superpowers/plans/` — implementation plans
- `docs/superpowers/handoffs/` — volatile state: in-flight work, open branches, "as of" notes.
  This is where it goes, NOT in `CLAUDE.md`.
- `docs/notes/` — dated working notes
- `CONTRIBUTING.md` — branch flow. **Never push directly to `main`.**

## Repo setup scripts (template-derived repos)

- `scripts/init-repo.sh <python|node|next> [--team <slug>]` — selects the stack and creates
  `dev`/`staging`/`main`. **Run it from `dev`:** the repo's default branch is `main`, so a fresh
  "Use this template" copy lands you on `main` and the script refuses to run (it cuts `staging` and
  `main` *from* `dev`). Start with:

      git checkout -b dev
      ./scripts/init-repo.sh <python|node|next>

  The default branch is `main` on purpose — Vercel and most tooling take the **production** branch
  from the repository default, so a repo defaulting to `dev` would deploy every merged PR straight
  to production. See `CONTRIBUTING.md`. **`--team` changes GitHub permissions:** if the named team exists but
  lacks write access to this repo, the script **grants it push (write) access**
  (`PUT orgs/Avenue-Z/teams/<slug>/repos/<owner>/<repo>`) before writing `.github/CODEOWNERS`.
  It does this rather than merely warning, because GitHub *silently ignores* a CODEOWNERS entry
  naming a team without write access — a warning nobody actions leaves a file that does not even
  route a reviewer. Granting needs repo-admin or org-owner rights; if it fails, the script refuses
  to write CODEOWNERS at all. Omit `--team` and no permissions are touched.
  **CODEOWNERS routes reviewers; it does not require their approval** — the ruleset ships
  `required_approving_review_count: 0`. See `SECURITY.md` before relying on it as a control.
- `scripts/apply-rulesets.sh [--dry-run]` — applies branch protection **to this repo**, where the
  plan allows it, and prints what it skipped. Touches nothing else.
- `scripts/link-vercel.sh [--dry-run]` — (`next` stack) links this repo to a Vercel project.
  **Linking is easy; deploying is a reviewed code change.** It never runs `vercel deploy`, and it
  refuses to link unless the default branch is `main` — Vercel takes its **production** branch from
  the repository default branch, so a repo defaulting to `dev` would deploy every merged PR straight
  to production. `vercel.json` ships `"deploymentEnabled": false`, so a freshly linked project
  deploys **nothing**. Turning a branch on means editing `vercel.json`, which means a PR.
- `scripts/apply-org-ruleset.sh [--dry-run]` — applies the org ruleset to **every repository in
  Avenue-Z**. Deliberately hard to run, and separate from the command above so that it is not one
  flag away from it: there is **no `--yes` and no non-interactive path**, so it cannot run from CI
  or be replayed out of shell history — you must type a challenge phrase naming the live repo
  count. It also **refuses outright** to apply a ruleset that declares required status checks,
  since almost no repo in the org ships those workflows and a required check that never reports
  hangs every PR pending forever.
