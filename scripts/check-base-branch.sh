#!/usr/bin/env bash
# Decision logic for the guard-base-branch workflow.
#
# Enforces the branch-promotion matrix from CONTRIBUTING.md:
#   feat/* | fix/* | docs/* | chore/* | ci/* | dependabot/*  ->  dev
#   dev                                                       ->  staging
#   staging                                                   ->  main
#
# Any other head-branch prefix FAILS CLOSED (exit 1).
#
# Usage: check-base-branch.sh <head_ref> <base_ref>
set -euo pipefail

head_ref="${1:?usage: check-base-branch.sh <head_ref> <base_ref>}"
base_ref="${2:?usage: check-base-branch.sh <head_ref> <base_ref>}"

case "$head_ref" in
  feat/*|fix/*|docs/*|chore/*|ci/*|dependabot/*) want=dev ;;
  dev)                                           want=staging ;;
  staging)                                       want=main ;;
  *)
    echo "::error::Unrecognized branch prefix '${head_ref}'. This guard FAILS CLOSED."
    echo "Allowed: feat/ fix/ docs/ chore/ ci/ dependabot/ — or dev, staging."
    echo "Need a new prefix? Add it to the case statement in scripts/check-base-branch.sh (and to the matrix in CONTRIBUTING.md)."
    exit 1
    ;;
esac

if [ "$base_ref" != "$want" ]; then
  echo "::error::'${head_ref}' must target '${want}', not '${base_ref}'. See CONTRIBUTING.md."
  exit 1
fi

echo "OK: '${head_ref}' -> '${base_ref}'"
