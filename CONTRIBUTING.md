# Contributing

## Branch flow

    feat/* | fix/* | docs/* | chore/* | ci/* | dependabot/*  →  dev  →  staging  →  main

- **`dev`** — integration branch. **Open your PR here.**

  Note the repo's *GitHub default branch* is `main`, not `dev`. That is deliberate: Vercel (and
  most tooling) takes the **production** branch from the repository default, so a repo defaulting
  to `dev` would deploy every merged PR straight to production. The cost is that a PR opened in the
  GitHub UI targets `main` — **change the base to `dev`** with the dropdown next to the title, or
  use `gh pr create --base dev`. If you forget, `guard-base-branch` fails the PR loudly; it re-runs
  when you change the base.
- **`staging`** — pre-prod soak / QA. Receives PRs from `dev` only.
- **`main`** — production. Receives PRs from `staging` only.

`guard-base-branch` fails any PR whose base is wrong for its head, and **fails closed on an
unrecognized branch prefix**. Need a new prefix? Add it to the `case` statement in
`scripts/check-base-branch.sh` (and to the matrix above) in a PR.

The guard reads its decision script from the **base** branch, so a PR cannot rewrite the rule it
is being judged against. It cannot, however, defend against a PR that edits
`.github/workflows/guard-base-branch.yml` itself — Actions runs the workflow file from the PR's
head, and **nothing in this repo's configuration forces anyone to review that.** `CODEOWNERS`
routes such a PR to a reviewer; it does not require their approval. Review any PR touching
`.github/` by convention, and read `SECURITY.md` before assuming you are protected from one.

## Never push directly to main

Every change reaches `main` through the chain above. No exceptions.

## Start every session by syncing

    git fetch --all --prune
    git log origin/dev..HEAD        # what you have that origin does not

## Repo setup scripts change real GitHub state

`scripts/init-repo.sh --team <slug>` does not just write `.github/CODEOWNERS` — if the team lacks
write access to this repo, it **grants the team push (write) access** on GitHub. That is a real
permission change, made because GitHub silently ignores a CODEOWNERS entry naming a team without
write access. Omit `--team` if you do not want it.

`scripts/apply-rulesets.sh` only ever touches **the repo you are standing in**.

The org-wide apply is a **separate script**, `scripts/apply-org-ruleset.sh`, and it is meant to be
awkward. It applies a ruleset to **every repository in Avenue-Z**, so it has no `--yes`, no
environment-variable override, and no non-interactive path at all — it cannot run from CI, and
there is no one-liner to replay out of your shell history. It lists every repo it would hit and
makes you type a challenge phrase that names the live repo count. If you find yourself wanting to
automate it, that is the feeling the design is for.

## Commits

`feat:` `fix:` `docs:` `chore:` `ci:` `test:` — imperative mood, one logical change.

## Before you open a PR

- Tests pass.
- Lint passes (`ruff check` / `npm run lint`).
- No credentials. `secret-scan` will fail the PR; a key that reached the remote is **burned and
  must be rotated**, even if the PR is never merged. See SECURITY.md.

## Releasing `contract-core`

A release is an **annotated git tag `vX.Y.Z` cut on `main`**. There is no wheel, no package index,
and no publish step — the tag *is* the version, and consumers pin
`contract-core @ git+https://github.com/Avenue-Z/data-contract@vX.Y.Z`.

1. In a normal PR, bump `version` in `pyproject.toml` **and** `__version__` in
   `src/contract_core/__init__.py` (a test fails if they skew), and move the `CHANGELOG.md`
   entry from *unreleased* to the version being cut. `CHANGELOG.md` **is** the release notes —
   there is no index page to carry them, and `docs/consuming-repo-setup.md` sends consumers
   there before they move a pin. `contract-core` is pre-1.0: under
   0.x semantics a **minor** bump may carry breaking changes — including a change to the public
   surface, which `tests/test_public_api.py` blocks until someone updates the frozen set
   deliberately.
2. Land it through the normal chain: `dev` → `staging` → `main`. **Never push to `main`.**
3. Tag the merge commit on `main`:

       git fetch --all --prune
       git tag -a v0.1.0 <sha-on-main> -m "contract-core v0.1.0"
       git push origin v0.1.0

4. Run the first-release smoke test in `docs/consuming-repo-setup.md` §5 — it is the only check
   that covers the authenticated `git+https` fetch, which no automated test can run before the tag
   exists.
