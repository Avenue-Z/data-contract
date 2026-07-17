# template-docs/ — the template's OWN design docs

The specs and plans that describe **repo-template itself**: how it was designed, and the review
logs behind each decision.

These live here, **not** in `docs/superpowers/{specs,plans}/`, on purpose. Those two dirs are the
generated repo's own workspace — an adopter may write their first spec there before (or while)
running `scripts/init-repo.sh`. `init-repo.sh` removes this whole directory with a single
`rm -rf template-docs`, so a generated repo carries none of the template's design history and
nothing the adopter wrote is ever at risk of deletion.

**Authoring a new design doc for the template? Put it here** — `template-docs/specs/` or
`template-docs/plans/`, not `docs/superpowers/specs/`. `template-tests/test_init_repo.sh` fails if a
dated design doc is left behind in `docs/superpowers/{specs,plans}/` after an init, which is the
guard that keeps a misplaced template spec from shipping into every generated repo.

- `specs/` — design specs, written before the plan. `YYYY-MM-DD-<topic>-design.md`
- `plans/` — implementation plans. One per feature. `YYYY-MM-DD-<feature>.md`
