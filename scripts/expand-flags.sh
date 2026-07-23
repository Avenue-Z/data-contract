#!/usr/bin/env bash
# scripts/expand-flags.sh <flag-name>
#
# Turn a newline-delimited value list on stdin into the argv a REPEATABLE click option needs —
# `--schemas a --schemas b` — emitted NUL-delimited so the caller reads it with `mapfile -d ''` and
# every value survives intact (a path may contain spaces).
#
# The load-bearing behavior is SKIPPING BLANK LINES. A GitHub `with:` block written as
#     schemas: |
#       schemas
# arrives with a trailing newline; without the skip that becomes `--schemas ""`, which trips
# click.Path(exists=True) and fails the gate on a VALID contract — a false red, the worst thing a
# gate can do. This lives in a script (not inline workflow YAML) so tests exercise the SAME logic the
# workflow runs — the scripts/ci-aggregate-gate.sh / check-base-branch.sh pattern.
set -euo pipefail

[ "$#" -eq 1 ] || { echo "usage: expand-flags.sh <flag-name>" >&2; exit 2; }
flag="$1"

# `|| [ -n "$line" ]` so a final line with no trailing newline is still processed.
while IFS= read -r line || [ -n "${line}" ]; do
  # Skip blank / whitespace-only lines — the false-red guard.
  [ -n "${line//[[:space:]]/}" ] || continue
  printf '%s\0%s\0' "${flag}" "${line}"
done
